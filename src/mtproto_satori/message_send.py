import base64
import mimetypes
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal, cast

from graia.amnesia.builtins.aiohttp import AiohttpClientService
from launart import Launart
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
  InlineKeyboardButton,
  InlineKeyboardButtonBuy,
  InlineKeyboardMarkup,
  InputMediaAnimation,
  InputMediaAudio,
  InputMediaDocument,
  InputMediaPhoto,
  InputMediaVideo,
  Message,
)
from satori.model import MessageObject
from satori.parser import Element, escape, parse
from yarl import URL

from mtproto_satori.message_receive import parse_message


@dataclass
class DownloadedFile:
  filename: str
  data: bytes
  mime: str


BASE64_HEADER = re.compile(r"^data:([\w/.+-]+);base64,")


async def get_file(url: str, name: str, timeout: int) -> DownloadedFile:
  if match := BASE64_HEADER.match(url):
    mime = match[1]
    data = base64.b64decode(BASE64_HEADER.sub("", url))
    if not name:
      ext = mimetypes.guess_extension(mime) or ".bin"
      name = "file" + ext
  elif url.startswith("file:"):
    path = Path.from_uri(url)
    mime = mimetypes.guess_file_type(path)[0] or "application/octet-stream"
    with path.open("rb") as f:
      data = f.read()
    if not name:
      name = path.name
  else:
    manager = Launart.current()
    aiohttp = manager.get_component(AiohttpClientService)
    parsed = URL(url)
    async with aiohttp.session.get(parsed) as response:
      data = await response.read()
    mime = response.headers.get("Content-Type", "application/octet-stream")
    mime = re.split(r"[;,]", mime, 1)[0]
    if not name:
      name = parsed.name
  return DownloadedFile(name, data, mime)


InputMediaAny = (
  InputMediaAnimation | InputMediaAudio | InputMediaDocument | InputMediaPhoto | InputMediaVideo
)


class MessageEncoder:
  def __init__(self) -> None:
    self.content = ""
    self.asset = list[Element]()
    self.mode: Literal["figure", "default"] = "default"
    self.reply = ""
    self.rows = list[list[InlineKeyboardButton | InlineKeyboardButtonBuy]]()

  async def visit(self, element: Element) -> None:
    if element.type == "text":
      self.content += escape(element.attrs["text"])
    elif element.type == "br":
      self.content += "\n"
    elif element.type == "p":
      if self.content.endswith("\n"):
        self.content += "\n"
      await self.render(element.children)
      if self.content.endswith("\n"):
        self.content += "\n"
    elif element.type in ("b", "strong", "i", "em", "u", "ins", "s", "del", "a"):
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
    elif element.type == "code-block":
      if "lang" in element.attrs:
        attrs = f' class="language-{element.attrs["lang"]}"'
      else:
        attrs = ""
      self.content += f"<pre><code{attrs}>"
      await self.render(element.children)
      self.content += "</code></pre>"
    elif element.type == "at":
      if "id" in element.attrs:
        id = element.attrs["id"]
        name = element.attrs.get("name", id)
        self.content += f'<a href="tg://user?id={id}">@{escape(name)}</a>'
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
  def __init__(self, client: Client, self_id: int, channel_id: int) -> None:
    super().__init__()
    self.result = list[MessageObject]()
    self.client = client
    self.self_id = self_id
    self.channel_id = channel_id

  def add_result(self, result: Message) -> None:
    self.result.append(parse_message(self.self_id, result))

  async def flush(self) -> None:
    if not (self.content or self.asset):
      return
    if self.rows and not self.rows[-1]:
      self.rows.pop()
    if self.asset:
      animations = list[InputMediaAnimation]()
      others = list[InputMediaAny]()
      for i, element in enumerate(self.asset):
        file = await get_file(
          element.attrs.get("src") or element.attrs["url"],
          element.attrs.get("title", ""),
          int(element.attrs.get("timeout", 0)),
        )
        data = BytesIO(file.data)
        data.name = str(i) + file.filename
        if file.mime == "image/gif":
          animations.append(InputMediaAnimation(data, has_spoiler="spoiler" in element.attrs))
        elif element.type in ("img", "image"):
          others.append(InputMediaPhoto(data, has_spoiler="spoiler" in element.attrs))
        elif element.type == "audio":
          others.append(InputMediaAudio(data))
        elif element.type == "video":
          others.append(InputMediaVideo(data, has_spoiler="spoiler" in element.attrs))
        elif element.type == "file":
          others.append(InputMediaDocument(data))

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
        reply_markup=InlineKeyboardMarkup(self.rows)
        if self.rows and self.rows[0]
        else cast(InlineKeyboardMarkup, None),
      )
      self.add_result(result)
    self.reply = None
    self.content = ""
    self.rows = []
    self.asset = []


async def send_message(
  client: Client,
  self_id: int,
  channel_id: int,
  message: str,
) -> list[MessageObject]:
  elements = parse(message)
  encoder = SendMessageEncoder(client, self_id, channel_id)
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
  encoder = MessageEncoder()
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
