from dataclasses import dataclass
from typing import Any, Literal, cast

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message, MessageEntity, User
from satori.element import (
  At,
  Audio,
  Bold,
  Br,
  Code,
  Custom,
  Element,
  File,
  Image,
  Italic,
  Link,
  Quote,
  Spoiler,
  Strikethrough,
  Text,
  Underline,
  Video,
)
from satori.model import MessageObject

from mtproto_satori.const import PLATFORM
from mtproto_satori.user import parse_user


@dataclass
class Breakpoint:
  mode: Literal["start", "end"]
  pos: int
  entity: MessageEntity | None

  def __lt__(self, other: "Breakpoint") -> bool:
    return self.pos < other.pos


@dataclass
class Status:
  bold: bool = False
  italic: bool = False
  underline: bool = False
  strikethrough: bool = False
  code: bool = False
  pre: bool = False
  spoiler: bool = False
  mention: bool = False
  link: str | None = None
  user: User | None = None


def parse_text(text: str, entities: list[MessageEntity]) -> list[Element]:
  breakpoints = list[Breakpoint]()
  for entity in entities or []:
    if entity.type in (MessageEntityType.BOLD, MessageEntityType.ITALIC, MessageEntityType.UNDERLINE, MessageEntityType.STRIKETHROUGH, MessageEntityType.CODE, MessageEntityType.PRE, MessageEntityType.SPOILER, MessageEntityType.MENTION, MessageEntityType.TEXT_LINK, MessageEntityType.TEXT_MENTION):
      breakpoints.append(Breakpoint("start", entity.offset, entity))
      breakpoints.append(Breakpoint("end", entity.offset + entity.length, entity))
  for i, ch in enumerate(text):
    if ch == "\n":
      breakpoints.append(Breakpoint("start", i, None))
      breakpoints.append(Breakpoint("end", i + 1, None))
  breakpoints.sort()

  status = Status()
  elements = list[Element]()
  last_pos = 0
  for breakpoint in breakpoints:
    if breakpoint.pos > last_pos:
      content = text[last_pos:breakpoint.pos]
      element = Text(content)
      if status.bold:
        element = Bold(element)
      if status.italic:
        element = Italic(element)
      if status.underline:
        element = Underline(element)
      if status.strikethrough:
        element = Strikethrough(element)
      if status.code:
        element = Code(element)
      if status.pre:
        element = Custom("pre", None, [element])
      if status.spoiler:
        element = Spoiler(cast(Any, element))
      if status.mention:
        element = At(name=content[1:])
      if status.link:
        new_element = Link(status.link)
        element.children.append(element)
        element = new_element
      if status.user:
        new_element = At(id=str(status.user.id), name=status.user.username)
        new_element.children.append(element)
        element = new_element
      if content == "\n":
        element = Br()
      elements.append(element)
    if breakpoint.entity:
      if breakpoint.entity.type == MessageEntityType.BOLD:
        status.bold = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.ITALIC:
        status.italic = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.UNDERLINE:
        status.underline = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.STRIKETHROUGH:
        status.strikethrough = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.CODE:
        status.code = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.PRE:
        status.pre = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.SPOILER:
        status.spoiler = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.MENTION:
        status.mention = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.TEXT_LINK:
        status.link = breakpoint.entity.url if breakpoint.mode == "start" else None
      elif breakpoint.entity.type == MessageEntityType.TEXT_MENTION:
        status.user = breakpoint.entity.user if breakpoint.mode == "start" else None
    last_pos = breakpoint.pos
  if last_pos < len(text):
    elements.append(Text(text[last_pos:]))
  return elements


@dataclass
class ParseResult:
  elements: list[Element]
  quote: MessageObject | None


def parse_message(self_id: int, message: Message) -> MessageObject:
  elements = []

  if message.reply_to_message and not (message.is_topic_message and message.reply_to_message.forum_topic_created):
    quote_message = parse_message(self_id, message.reply_to_message)
    quote_user = parse_user(self_id, message.reply_to_message.from_user)
    quote_elements = list[str | Element]()
    quote_elements.append(Custom("user", {
      "id": quote_user.id,
      "name": quote_user.name,
      "nick": quote_user.nick,
      "avatar": quote_user.avatar,
      "is-bot": quote_user.is_bot,
    }))
    quote_elements.extend(quote_message.content)
    elements.append(Quote(str(message.reply_to_message.id), content=quote_elements))

  elements.extend(parse_text(message.text or message.caption or "", message.entities or message.caption_entities or []))

  if message.caption:
    elements.append(Text(" "))

  if message.location:
    elements.append(Custom("location", {"lat": message.location.latitude, "lon": message.location.longitude}))
  elif message.photo:
    elements.append(Image(f"internal:{PLATFORM}/{self_id}/{message.photo.file_id}"))
  elif message.sticker:
    elements.append(Image(f"internal:{PLATFORM}/{self_id}/{message.sticker.file_id}", message.sticker.file_name))
  elif message.voice:
    elements.append(Audio(f"internal:{PLATFORM}/{self_id}/{message.voice.file_id}"))
  elif message.animation:
    elements.append(Image(f"internal:{PLATFORM}/{self_id}/{message.animation.file_id}", message.animation.file_name))
  elif message.video:
    elements.append(Video(f"internal:{PLATFORM}/{self_id}/{message.video.file_id}", message.video.file_name))
  elif message.document:
    elements.append(File(f"internal:{PLATFORM}/{self_id}/{message.document.file_id}", message.document.file_name))
  elif message.audio:
    elements.append(Audio(f"internal:{PLATFORM}/{self_id}/{message.audio.file_id}", message.audio.file_name))

  return MessageObject.from_elements(str(message.id), elements)
