import base64
import mimetypes
import re
from collections.abc import Iterable
from io import BytesIO
from itertools import chain
from pathlib import Path
from tempfile import TemporaryFile
from typing import Any, BinaryIO, Literal, cast

import aiohttp
import puremagic
from graia.amnesia.builtins.aiohttp import AiohttpClientService
from launart import Launart
from PIL import Image
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
  InlineKeyboardButton,
  InlineKeyboardMarkup,
  InputMediaAnimation,
  InputMediaAudio,
  InputMediaDocument,
  InputMediaPhoto,
  InputMediaVideo,
  Message,
  Sticker,
  User,
)
from satori.model import MessageObject
from satori.parser import Element, escape, parse
from yarl import URL

from mtproto_satori.message_receive import parse_message

BASE64_HEADER = re.compile(r"^data:([\w/.+-]+);base64,")
_aiohttp: aiohttp.ClientSession | None = None


def get_aiohttp() -> aiohttp.ClientSession:
  try:
    manager = Launart.current()
    client = manager.get_component(AiohttpClientService).session
  except LookupError, ValueError:
    global _aiohttp
    if not _aiohttp:
      _aiohttp = aiohttp.ClientSession()
    client = _aiohttp
  return client


async def get_media(session_name: str, url: str, name: str, timeout: float) -> BinaryIO:
  if match := BASE64_HEADER.match(url):
    data = base64.b64decode(BASE64_HEADER.sub("", url))
    if not name:
      try:
        ext = puremagic.from_string(data)
      except puremagic.PureError:
        ext = mimetypes.guess_extension(match[1]) or ".bin"
      name = "file" + ext
    file = BytesIO(data)
    file.name = name
  elif url.startswith("file:"):
    path = Path.from_uri(url)
    file = path.open("rb")
    if name:
      cast(Any, file.raw).name = name
  else:
    parsed = URL(url)
    client = get_aiohttp()
    dir = Path(f"files_{session_name}")
    dir.mkdir(exist_ok=True, parents=True)
    file = TemporaryFile(dir=dir)
    async with client.get(parsed) as response:
      async for chunk in response.content.iter_any():
        file.write(chunk)
    if not name:
      name = parsed.name
    file.name = name
  return file


def image_mime_valid(mime: str) -> bool:
  return mime in ("image/jpeg", "image/png", "image/gif")


async def get_image(
  session_name: str,
  url: str,
  name: str,
  timeout: float,
) -> tuple[BinaryIO, str]:
  dir = Path(f"files_{session_name}")
  dir.mkdir(exist_ok=True, parents=True)
  if match := BASE64_HEADER.match(url):
    data = base64.b64decode(BASE64_HEADER.sub("", url))
    if magic := puremagic.magic_string(data):
      magic = max(magic)
      mime = magic.mime_type
      ext = magic.extension
    else:
      mime = match[1]
      ext = mimetypes.guess_extension(mime) or ".bin"
    file = BytesIO(data)
    if not image_mime_valid(mime):
      im = Image.open(file)
      file = BytesIO()
      im.save(file, "PNG")
      mime = "image/png"
      ext = ".png"
    if name:
      if not name.endswith(ext):
        name += ext
    else:
      name = "file" + ext
    file.name = name
  elif url.startswith("file:"):
    path = Path.from_uri(url)
    if magic := puremagic.magic_file(path):
      magic = max(magic)
      mime = magic.mime_type
      ext = magic.extension
    else:
      mime = "application/octet-stream"
      ext = ".bin"
    if image_mime_valid(mime):
      file = path.open("rb")
    else:
      file = TemporaryFile(dir=dir)
      im = Image.open(path)
      im.save(file, "PNG")
      mime = "image/png"
      ext = ".png"
    if not name:
      name = path.name
    if not name.endswith(ext):
      name += ext
    if isinstance(file, BytesIO):
      file.name = name
    else:
      cast(Any, file.raw).name = name
  else:
    parsed = URL(url)
    file = TemporaryFile(dir=dir)
    async with get_aiohttp().get(parsed) as response:
      async for chunk in response.content.iter_any():
        file.write(chunk)
    file.seek(0)
    if magic := puremagic.magic_stream(file):
      magic = max(magic)
      mime = magic.mime_type
      ext = magic.extension
    else:
      mime = "application/octet-stream"
      ext = ".bin"
    if not image_mime_valid(mime):
      im = Image.open(file)
      im.save(file, "PNG")
      mime = "image/png"
      ext = ".png"
    if not name:
      name = parsed.name
    if not name.endswith(ext):
      name += ext
    cast(Any, file.raw).name = name
  return file, mime


InputMediaNotAnimation = InputMediaAudio | InputMediaDocument | InputMediaPhoto | InputMediaVideo


class MessageEncoder:
  def __init__(self, emojis: dict[int, Sticker], users: dict[int | str, User]) -> None:
    self.content = ""
    self.asset = list[Element]()
    self.mode: Literal["figure", "default"] = "default"
    self.reply = ""
    self.rows = list[list[InlineKeyboardButton]]()
    self.emojis = emojis
    self.users = users

  def _get_emoji_name(self, emoji_id: int) -> str | None:
    if emoji := self.emojis.get(emoji_id):
      return emoji.emoji
    return None

  def _get_user_name(self, user_id: int | str) -> str | None:
    if user := self.users.get(user_id):
      if user.username:
        return f"@{user.username}"
      if full_name := user.full_name:
        return full_name
    return None

  async def visit(self, element: Element) -> None:
    if element.type == "text":
      self.content += escape(element.attrs["text"])
    elif element.type == "br":
      self.content += "\n"
    elif element.type == "p":
      if not self.content.endswith("\n"):
        self.content += "\n"
      await self.render(element.children)
      if not self.content.endswith("\n"):
        self.content += "\n"
    elif element.type == "a":
      if href := element.attrs.get("href"):
        attrs = f' href="{escape(href, True)}"'
      else:
        attrs = ""
      self.content += f"<a{attrs}>"
      await self.render(element.children)
      self.content += "</a>"
    elif element.type in ("b", "strong", "i", "em", "u", "ins", "s", "del"):
      self.content += f"<{element.type}>"
      await self.render(element.children)
      self.content += f"</{element.type}>"
    elif element.type == "spl":
      self.content += "<tg-spoiler>"
      await self.render(element.children)
      self.content += "</tg-spoiler>"
    elif element.type == "code":
      self.content += "<code>"
      if "content" in element.attrs:
        self.content += escape(element.attrs["content"])
      else:
        await self.render(element.children)
      self.content += "</code>"
    elif element.type in ("pre", "code-block"):
      if lang := element.attrs.get("lang"):
        attrs = f' class="language-{escape(lang, True)}"'
      else:
        attrs = ""
      self.content += f"<pre><code{attrs}>"
      await self.render(element.children)
      self.content += "</code></pre>"
    elif element.type == "at":
      if id := element.attrs.get("id"):
        try:
          id = int(id)
        except ValueError:
          # ID 代表用户名，始终获取用户 ID，用户名不存在就瞎填一个 ID
          username = id.removeprefix("@")
          id = user.id if (user := self.users.get(username)) else escape(f"@{username}", True)
          display = element.attrs.get("name") or f"@{username}"
          self.content += f'<a href="tg://user?id={id}">{escape(display)}</a>'
        else:
          # ID 代表用户 ID，使用 name 指定的名字，没有再获取
          display = element.attrs.get("name") or self._get_user_name(id) or "User"
          self.content += f'<a href="tg://user?id={id}">{escape(display)}</a>'
    elif element.type == "emoji":
      if id := element.attrs.get("id"):
        id = int(id)
        name = element.attrs.get("name") or self._get_emoji_name(id) or "😀"
        self.content += f'<tg-emoji emoji-id="{id}">{escape(name)}</tg-emoji>'
    elif element.type in ("img", "image", "audio", "video", "file"):
      self.asset.append(element)
    elif element.type == "figure":
      await self.flush()
      self.mode = "figure"
      await self.render(element.children)
      await self.flush()
      self.mode = "default"
    elif element.type == "quote":
      if "id" in element.attrs:
        await self.flush()
        self.reply = element.attrs["id"]
      else:
        self.content += "<blockquote>"
        await self.render(element.children)
        self.content += "</blockquote>"
    elif element.type == "button":
      if not self.rows:
        self.rows.append([])
      row = self.rows[-1]
      if len(row) >= 5:
        row = []
        self.rows.append(row)
      label = element.dumps(True)
      if element.attrs["type"] == "link":
        button = InlineKeyboardButton(
          label,
          url=element.attrs["href"],
        )
      elif element.attrs["type"] == "input":
        button = InlineKeyboardButton(
          label,
          switch_inline_query_current_chat=element.attrs["text"],
        )
      else:
        button = InlineKeyboardButton(
          label,
          callback_data=element.attrs["id"],
        )
      row.append(button)
    elif element.type == "button-group":
      self.rows.append([])
      await self.render(element.children)
      self.rows.append([])
    elif element.type == "message":
      if self.mode == "figure":
        await self.render(element.children)
        self.content += "\n"
      else:
        await self.flush()
        await self.render(element.children)
        await self.flush()
    else:
      await self.render(element.children)

  async def flush(self) -> None:
    pass

  async def render(self, elements: list[Element]) -> None:
    for element in elements:
      await self.visit(element)


class SendMessageEncoder(MessageEncoder):
  def __init__(
    self,
    client: Client,
    me: User,
    channel_id: int,
    thread_id: int | None,
    emojis: dict[int, Sticker],
    users: dict[int | str, User],
  ) -> None:
    super().__init__(emojis, users)
    self.result = list[MessageObject]()
    self.client = client
    self.me = me
    self.channel_id = channel_id
    self.thread_id = thread_id

  def add_result(self, result: Message) -> None:
    self.result.append(parse_message(self.me, result))

  async def flush(self) -> None:
    if not (self.content or self.asset):
      return
    if self.rows and not self.rows[-1]:
      self.rows.pop()
    if self.asset:
      animations = list[InputMediaAnimation]()
      others = list[InputMediaNotAnimation]()
      for i, element in enumerate(self.asset):
        src = element.attrs.get("src") or element.attrs["url"]
        title = element.attrs.get("title", "")
        timeout = float(element.attrs.get("timeout", 0))
        if element.type in ("img", "image"):
          file, mime = await get_image(self.client.name, src, title, timeout)
          spoiler = "spoiler" in element.attrs
          if mime == "image/gif":
            animations.append(InputMediaAnimation(file, has_spoiler=spoiler))
          else:
            others.append(InputMediaPhoto(file, has_spoiler=spoiler))
        elif element.type == "audio":
          file = await get_media(self.client.name, src, title, timeout)
          others.append(InputMediaAudio(file))
        elif element.type == "video":
          file = await get_media(self.client.name, src, title, timeout)
          spoiler = "spoiler" in element.attrs
          others.append(InputMediaVideo(file, has_spoiler=spoiler))
        elif element.type == "file":
          file = await get_media(self.client.name, src, title, timeout)
          others.append(InputMediaDocument(file))

      results = list[Message]()

      has_buttons = self.rows and self.rows[0]
      if not has_buttons:
        if others:
          others[0].caption = self.content
          others[0].parse_mode = cast(str, ParseMode.HTML)
        else:
          animations[0].caption = self.content
          animations[0].parse_mode = cast(str, ParseMode.HTML)

      if others:
        result = await self.client.send_media_group(
          self.channel_id,
          others,
          reply_to_message_id=int(self.reply) if self.reply else cast(int, None),
          message_thread_id=cast(int, self.thread_id),
        )
        results.extend(result)

      for file in animations:
        if results:
          reply = results[0].id
        elif self.reply:
          reply = int(self.reply)
        else:
          reply = cast(int, None)
        result = await self.client.send_animation(
          self.channel_id,
          file.media,
          file.caption,
          parse_mode=ParseMode.HTML,
          has_spoiler=file.has_spoiler,
          reply_to_message_id=reply,
          message_thread_id=cast(int, self.thread_id),
        )
        results.append(cast(Message, result))

      if has_buttons:
        results.append(
          await self.client.send_message(
            self.channel_id,
            self.content,
            ParseMode.HTML,
            reply_to_message_id=results[0].id,
            reply_markup=InlineKeyboardMarkup(self.rows),
            message_thread_id=cast(int, self.thread_id),
          )
        )

      for result in results:
        self.add_result(result)
    else:
      result = await self.client.send_message(
        self.channel_id,
        self.content,
        ParseMode.HTML,
        reply_to_message_id=int(self.reply) if self.reply else cast(int, None),
        message_thread_id=cast(int, self.thread_id),
        reply_markup=InlineKeyboardMarkup(self.rows)
        if self.rows and self.rows[0]
        else cast(InlineKeyboardMarkup, None),
      )
      self.add_result(result)
    self.reply = None
    self.content = ""
    self.rows = []
    self.asset = []


def extract_emojis_without_name(element: Element | Iterable[Element]) -> set[int]:
  if isinstance(element, Element):
    if element.type == "emoji":
      emoji_id = element.attrs.get("id")
      if emoji_id and not element.attrs.get("name"):
        try:
          return {int(emoji_id)}
        except ValueError:
          pass
      return set()
    element = element.children
  return set(chain.from_iterable(extract_emojis_without_name(element) for element in element))


async def fetch_emojis(client: Client, emojis: set[int]) -> dict[int, Sticker]:
  return (
    {
      sticker.custom_emoji_id: sticker
      for sticker in await client.get_custom_emoji_stickers(list(emojis))
      if sticker.custom_emoji_id
    }
    if emojis
    else {}
  )


def extract_users_without_id_or_name(element: Element | Iterable[Element]) -> set[int | str]:
  if isinstance(element, Element):
    if element.type == "at":
      if user_id := element.attrs.get("id"):
        try:
          user_id = int(user_id)
        except ValueError:
          # 当 ID 代表用户名时，获取所有用户
          return {user_id.removeprefix("@")}
        else:
          # 当 ID 代表用户 ID 时，只获取未指定 name 的用户
          return {user_id} if not element.attrs.get("name") else set()
      return set()
    element = element.children
  return set(chain.from_iterable(extract_users_without_id_or_name(element) for element in element))


async def fetch_users(client: Client, users: set[int | str]) -> dict[int | str, User]:
  if users:
    infos = cast(list[User], await client.get_users(users))
    results: dict[int | str, User] = {info.id: info for info in infos}
    results.update((info.username, info) for info in infos if info.username)
    return results
  return {}


async def send_message(
  client: Client,
  me: User,
  channel_id: int,
  thread_id: int | None,
  message: str,
) -> list[MessageObject]:
  elements = parse(message)
  emojis = await fetch_emojis(client, extract_emojis_without_name(elements))
  users = await fetch_users(client, extract_users_without_id_or_name(elements))
  encoder = SendMessageEncoder(client, me, channel_id, thread_id, emojis, users)
  await encoder.render(elements)
  await encoder.flush()
  return encoder.result


async def update_message(
  client: Client,
  channel_id: int,
  message_id: int,
  message: str,
) -> None:
  elements = parse(message)
  emojis = await fetch_emojis(client, extract_emojis_without_name(elements))
  users = await fetch_users(client, extract_users_without_id_or_name(elements))
  encoder = MessageEncoder(emojis, users)
  await encoder.render(elements)
  await client.edit_message_text(
    channel_id,
    message_id,
    encoder.content,
    ParseMode.HTML,
    reply_markup=InlineKeyboardMarkup(encoder.rows)
    if encoder.rows and encoder.rows[0]
    else cast(InlineKeyboardMarkup, None),
  )
