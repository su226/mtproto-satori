import base64
import mimetypes
import re
from collections.abc import AsyncGenerator, Iterable
from copy import copy
from dataclasses import dataclass, field
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
from pyrogram.enums import MessageEntityType
from pyrogram.types import (
  InlineKeyboardButton,
  InlineKeyboardMarkup,
  InputMediaAnimation,
  InputMediaAudio,
  InputMediaDocument,
  InputMediaPhoto,
  InputMediaVideo,
  Message,
  MessageEntity,
  Sticker,
  User,
)
from satori.model import MessageObject
from satori.parser import Element, parse
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


@dataclass
class MessagePack:
  content: str = ""
  utf16_len: int = 0
  entities: list[MessageEntity] = field(default_factory=list)
  assets: list[Element] = field(default_factory=list)
  reply: str = ""
  forward: str = ""
  button_rows: list[list[InlineKeyboardButton]] = field(default_factory=list)

  def push_text(self, text: str) -> None:
    self.content += text
    self.utf16_len += len(text.encode("utf-16-le")) // 2

  @staticmethod
  def merge(packs: Iterable[MessagePack]) -> MessagePack:
    result = MessagePack()
    for pack in packs:
      for entity in pack.entities:
        entity.offset += result.utf16_len
        result.entities.append(entity)
      result.push_text(pack.content)
      result.assets.extend(pack.assets)
      result.reply = result.reply or pack.reply
      result.forward = result.forward or pack.forward
      result.button_rows.extend(pack.button_rows)
    return result


class MessageEncoder:
  def __init__(self, emojis: dict[str, Sticker], users: dict[int | str, User]) -> None:
    self.current = MessagePack()
    self.packs = list[MessagePack]()
    self.entities_stack = list[MessageEntity]()
    self.mode: Literal["figure", "default"] = "default"
    self.emojis = emojis
    self.users = users

  def _get_emoji_name(self, emoji_id: str) -> str | None:
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

  def _push_entities_stack(self, entity: MessageEntity) -> None:
    entity.offset = self.current.utf16_len
    self.entities_stack.append(entity)

  def _pop_entities_stack(self) -> None:
    entity = self.entities_stack.pop()
    entity.length = self.current.utf16_len - entity.offset
    self.current.entities.append(entity)

  def visit(self, element: Element) -> None:
    if element.type == "text":
      self.current.push_text(element.attrs.get("text") or "")
    elif element.type == "br":
      self.current.push_text("\n")
    elif element.type == "p":
      if self.current.content and not self.current.content.endswith("\n"):
        self.current.push_text("\n")
      self.render(element.children)
      if self.current.content and not self.current.content.endswith("\n"):
        self.current.push_text("\n")
    elif element.type == "a":
      if href := element.attrs.get("href"):
        self._push_entities_stack(
          MessageEntity(type=MessageEntityType.TEXT_LINK, offset=0, length=0, url=href)
        )
        self.render(element.children)
        self._pop_entities_stack()
      else:
        self.render(element.children)
    elif element.type in ("b", "strong"):
      self._push_entities_stack(MessageEntity(type=MessageEntityType.BOLD, offset=0, length=0))
      self.render(element.children)
      self._pop_entities_stack()
    elif element.type in ("i", "em"):
      self._push_entities_stack(MessageEntity(type=MessageEntityType.ITALIC, offset=0, length=0))
      self.render(element.children)
      self._pop_entities_stack()
    elif element.type in ("u", "ins"):
      self._push_entities_stack(
        MessageEntity(type=MessageEntityType.UNDERLINE, offset=0, length=0)
      )
      self.render(element.children)
      self._pop_entities_stack()
    elif element.type in ("s", "del"):
      self._push_entities_stack(
        MessageEntity(type=MessageEntityType.STRIKETHROUGH, offset=0, length=0)
      )
      self.render(element.children)
      self._pop_entities_stack()
    elif element.type == "spl":
      self._push_entities_stack(MessageEntity(type=MessageEntityType.SPOILER, offset=0, length=0))
      self.render(element.children)
      self._pop_entities_stack()
    elif element.type == "code":
      self._push_entities_stack(MessageEntity(type=MessageEntityType.CODE, offset=0, length=0))
      if "content" in element.attrs:
        self.current.push_text(element.attrs["content"])
      else:
        self.render(element.children)
      self._pop_entities_stack()
    elif element.type in ("pre", "code-block"):
      if lang := element.attrs.get("lang"):
        self._push_entities_stack(
          MessageEntity(type=MessageEntityType.PRE, offset=0, length=0, language=lang)
        )
      else:
        self._push_entities_stack(MessageEntity(type=MessageEntityType.PRE, offset=0, length=0))
      self.render(element.children)
      self._pop_entities_stack()
    elif element.type == "at":
      if id_or_username := element.attrs.get("id"):
        try:
          id = int(id_or_username)
        except ValueError:
          # ID 代表用户名，始终获取用户 ID，用户名不存在就不生成 TEXT_MENTION
          username = id_or_username.removeprefix("@")
          if user := self.users.get(username):
            display = element.attrs.get("name") or f"@{username}"
            self._push_entities_stack(
              MessageEntity(type=MessageEntityType.TEXT_MENTION, offset=0, length=0, user=user)
            )
            self.current.push_text(display)
            self._pop_entities_stack()
          elif self.current.content and not self.current.content[-1].isspace():
            self.current.push_text(f" @{username} ")
          else:
            self.current.push_text(f"@{username} ")
        else:
          # ID 代表用户 ID，使用 name 指定的名字，没有再获取
          display = element.attrs.get("name") or self._get_user_name(id) or "User"
          self._push_entities_stack(
            MessageEntity(
              type=MessageEntityType.TEXT_MENTION,
              offset=0,
              length=0,
              user=User(id=id),
            )
          )
          self.current.push_text(display)
          self._pop_entities_stack()
    elif element.type == "emoji":
      if id := element.attrs.get("id"):
        name = element.attrs.get("name") or self._get_emoji_name(id) or "😀"
        self._push_entities_stack(
          MessageEntity(
            type=MessageEntityType.CUSTOM_EMOJI,
            offset=0,
            length=0,
            custom_emoji_id=id,
          )
        )
        self.current.push_text(name)
        self._pop_entities_stack()
    elif element.type in ("img", "image", "audio", "video", "file"):
      self.current.assets.append(element)
    elif element.type == "figure":
      self.flush()
      self.mode = "figure"
      self.render(element.children)
      self.flush()
      self.mode = "default"
    elif element.type == "quote":
      if "id" in element.attrs:
        self.flush()
        self.reply = element.attrs["id"]
      else:
        self._push_entities_stack(
          MessageEntity(type=MessageEntityType.BLOCKQUOTE, offset=0, length=0)
        )
        self.render(element.children)
        self._pop_entities_stack()
    elif element.type == "button":
      if not self.current.button_rows:
        self.current.button_rows.append([])
      row = self.current.button_rows[-1]
      if len(row) >= 5:
        row = []
        self.current.button_rows.append(row)
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
      self.current.button_rows.append([])
      self.render(element.children)
      self.current.button_rows.append([])
    elif element.type == "message":
      if self.mode == "figure":
        self.render(element.children)
        self.current.push_text("\n")
      else:
        self.flush()
        if element.attrs.get("forward") and (forward_id := element.attrs.get("id")):
          self.current.forward = forward_id
        else:
          self.render(element.children)
        self.flush()
    else:
      self.render(element.children)

  def flush(self) -> None:
    if not (self.current.content or self.current.assets or self.current.forward):
      return
    for entity in self.entities_stack:
      new_entity = copy(entity)
      new_entity.length = self.current.utf16_len - new_entity.offset
      self.current.entities.append(new_entity)
      entity.offset = 0
    if self.current.button_rows and not self.current.button_rows[-1]:
      self.current.button_rows.pop()
    self.packs.append(self.current)
    self.current = MessagePack()

  def render(self, elements: list[Element]) -> None:
    for element in elements:
      self.visit(element)


def extract_emojis_without_name(element: Element | Iterable[Element]) -> set[str]:
  if isinstance(element, Element):
    if element.type == "emoji":
      emoji_id = element.attrs.get("id")
      if emoji_id and not element.attrs.get("name"):
        try:
          return {emoji_id}
        except ValueError:
          pass
      return set()
    element = element.children
  return set(chain.from_iterable(extract_emojis_without_name(element) for element in element))


async def fetch_emojis(client: Client, emojis: set[str]) -> dict[str, Sticker]:
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
      if id_or_username := element.attrs.get("id"):
        try:
          id = int(id_or_username)
        except ValueError:
          # 当 ID 代表用户名时，获取所有用户
          return {id_or_username.removeprefix("@")}
        else:
          # 当 ID 代表用户 ID 时，只获取未指定 name 的用户
          return {id} if not element.attrs.get("name") else set()
      return set()
    element = element.children
  return set(chain.from_iterable(extract_users_without_id_or_name(element) for element in element))


async def fetch_users(client: Client, users: set[int | str]) -> dict[int | str, User]:
  if users:
    infos = await client.get_users(users)
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
) -> AsyncGenerator[tuple[Message, MessageObject], None]:
  elements = parse(message)
  emojis = await fetch_emojis(client, extract_emojis_without_name(elements))
  users = await fetch_users(client, extract_users_without_id_or_name(elements))
  encoder = MessageEncoder(emojis, users)
  encoder.render(elements)
  encoder.flush()

  for pack in encoder.packs:
    if pack.assets:
      animations = list[InputMediaAnimation]()
      others = list[InputMediaNotAnimation]()
      for element in pack.assets:
        src = element.attrs.get("src") or element.attrs["url"]
        title = element.attrs.get("title", "")
        timeout = float(element.attrs.get("timeout") or 0)
        if element.type in ("img", "image"):
          file, mime = await get_image(client.name, src, title, timeout)
          spoiler = "spoiler" in element.attrs
          if mime == "image/gif":
            animations.append(InputMediaAnimation(file, has_spoiler=spoiler))
          else:
            others.append(InputMediaPhoto(file, has_spoiler=spoiler))
        elif element.type == "audio":
          file = await get_media(client.name, src, title, timeout)
          others.append(InputMediaAudio(file))
        elif element.type == "video":
          file = await get_media(client.name, src, title, timeout)
          spoiler = "spoiler" in element.attrs
          others.append(InputMediaVideo(file, has_spoiler=spoiler))
        elif element.type == "file":
          file = await get_media(client.name, src, title, timeout)
          others.append(InputMediaDocument(file))

      has_buttons = pack.button_rows and pack.button_rows[0]
      if not has_buttons:
        if others:
          others[0].caption = pack.content
          others[0].caption_entities = pack.entities
        else:
          animations[0].caption = pack.content
          animations[0].caption_entities = pack.entities

      first: int | None = None
      reply = int(pack.reply) if pack.reply else cast(int, None)

      if others:
        group = await client.send_media_group(
          channel_id,
          others,
          reply_to_message_id=reply,
          message_thread_id=cast(int, thread_id),
        )
        first = group[0].id
        for result in group:
          yield (result, parse_message(me, result))

      for file in animations:
        if not file.media:
          continue
        result = cast(
          Message,
          await client.send_animation(
            channel_id,
            file.media,
            file.caption,
            caption_entities=cast(list[MessageEntity], file.caption_entities),
            has_spoiler=file.has_spoiler or False,
            reply_to_message_id=first or reply,
            message_thread_id=cast(int, thread_id),
          ),
        )
        if not first:
          first = result.id
        yield (result, parse_message(me, result))

      if has_buttons:
        result = await client.send_message(
          channel_id,
          pack.content,
          entities=pack.entities,
          reply_to_message_id=first,
          reply_markup=InlineKeyboardMarkup(pack.button_rows),
          message_thread_id=thread_id,
        )
        if not result:
          raise ValueError("Sent message has no receipt.")
        yield (result, parse_message(me, result))
    elif pack.forward:
      split_id = pack.forward.split(":", 1)
      if len(split_id) == 2:
        from_chat_id = int(split_id[0])
        message_id = int(split_id[1])
      else:
        from_chat_id = channel_id
        message_id = int(split_id[0])
      result = cast(
        Message,
        await client.forward_messages(
          channel_id,
          from_chat_id,
          message_id,
          cast(int, thread_id),
        ),
      )
      yield (result, parse_message(me, result))
    else:
      result = await client.send_message(
        channel_id,
        pack.content,
        entities=pack.entities,
        reply_to_message_id=int(pack.reply) if pack.reply else None,
        message_thread_id=thread_id,
        reply_markup=InlineKeyboardMarkup(pack.button_rows)
        if pack.button_rows and pack.button_rows[0]
        else None,
      )
      if not result:
        raise ValueError("Sent message has no receipt.")
      yield (result, parse_message(me, result))


async def update_message(
  client: Client,
  me: User,
  channel_id: int,
  message_id: int,
  message: str,
) -> tuple[Message, MessageObject]:
  elements = parse(message)
  emojis = await fetch_emojis(client, extract_emojis_without_name(elements))
  users = await fetch_users(client, extract_users_without_id_or_name(elements))
  encoder = MessageEncoder(emojis, users)
  encoder.render(elements)
  encoder.flush()

  pack = MessagePack.merge(encoder.packs)
  result = await client.edit_message_text(
    channel_id,
    message_id,
    pack.content,
    entities=pack.entities,
    reply_markup=InlineKeyboardMarkup(pack.button_rows)
    if pack.button_rows and pack.button_rows[0]
    else cast(InlineKeyboardMarkup, None),
  )
  return (result, parse_message(me, result))
