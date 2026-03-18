from dataclasses import dataclass
from typing import Any, Literal, cast

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message, MessageEntity
from pyrogram.types import User as TGUser
from satori.element import (
  At,
  Audio,
  Author,
  Bold,
  Br,
  Code,
  Custom,
  Element,
  Emoji,
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
from satori.model import MessageObject, User

from mtproto_satori.const import PLATFORM
from mtproto_satori.user import parse_guild_channel, parse_sender_chat, parse_user


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
  pre: str | None = None
  spoiler: bool = False
  mention: bool = False
  link: str | None = None
  user: TGUser | None = None
  emoji: int | None = None


def parse_text(text: str, entities: list[MessageEntity] | None) -> list[Element]:
  breakpoints = list[Breakpoint]()
  if entities:
    for entity in entities:
      if entity.type in (
        MessageEntityType.BOLD,
        MessageEntityType.ITALIC,
        MessageEntityType.UNDERLINE,
        MessageEntityType.STRIKETHROUGH,
        MessageEntityType.CODE,
        MessageEntityType.PRE,
        MessageEntityType.SPOILER,
        MessageEntityType.MENTION,
        MessageEntityType.TEXT_LINK,
        MessageEntityType.TEXT_MENTION,
        MessageEntityType.CUSTOM_EMOJI,
      ):
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
      content = text[last_pos : breakpoint.pos]
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
      if status.pre is not None:
        attrs = {"lang": status.pre} if status.pre != "" else {}
        element = Custom("pre", attrs, [element])
      if status.spoiler:
        element = Spoiler(cast(Any, element))
      if status.mention:
        username = content[1:]
        element = At(username, username)
      if status.link:
        new_element = Link(status.link)
        new_element.children.append(element)
        element = new_element
      if status.user:
        new_element = At(id=str(status.user.id), name=status.user.username)
        new_element.children.append(element)
        element = new_element
      if status.emoji:
        element = Emoji(str(status.emoji), name=content)
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
        status.pre = breakpoint.entity.language or "" if breakpoint.mode == "start" else None
      elif breakpoint.entity.type == MessageEntityType.SPOILER:
        status.spoiler = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.MENTION:
        status.mention = breakpoint.mode == "start"
      elif breakpoint.entity.type == MessageEntityType.TEXT_LINK:
        status.link = breakpoint.entity.url if breakpoint.mode == "start" else None
      elif breakpoint.entity.type == MessageEntityType.TEXT_MENTION:
        status.user = breakpoint.entity.user if breakpoint.mode == "start" else None
      elif breakpoint.entity.type == MessageEntityType.CUSTOM_EMOJI:
        status.emoji = breakpoint.entity.custom_emoji_id if breakpoint.mode == "start" else None
    last_pos = breakpoint.pos
  if last_pos < len(text):
    elements.append(Text(text[last_pos:]))
  return elements


def parse_message_sender(me: TGUser, message: Message) -> User:
  if message.sender_chat:
    return parse_sender_chat(me.id, message.sender_chat)
  if message.from_user:
    return parse_user(me.id, message.from_user)
  if message.outgoing:
    # 私聊发送的消息没有 from_user
    return parse_user(me.id, me)
  if message.chat:
    # 频道消息既没有 sender_chat 也没有 from_user
    return parse_sender_chat(me.id, message.chat)
  raise ValueError("Message has no sender.")


def parse_elements(me: TGUser, message: Message) -> list[Element]:
  elements = list[Element]()

  if message.reply_to_message and not (
    message.topic_message and message.reply_to_message.forum_topic_created
  ):
    if message.quote and message.quote.text:
      quote_message = parse_text(message.quote.text, message.quote.entities)
    else:
      quote_message = parse_elements(me, message.reply_to_message)
    quote_user = parse_message_sender(me, message.reply_to_message)
    quote_elements = list[str | Element]()
    quote_elements.append(Author(quote_user.id, quote_user.name, quote_user.avatar))
    quote_elements.extend(quote_message)
    if (
      message.chat
      and message.reply_to_message.chat
      and message.chat.id != message.reply_to_message.chat.id
    ):
      id = f"{message.reply_to_message.chat.id}:{message.reply_to_message.id}"
    else:
      id = str(message.reply_to_message.id)
    elements.append(Quote(id, content=quote_elements))

  elements.extend(
    parse_text(
      message.text or message.caption or "",
      message.entities or message.caption_entities,
    )
  )

  if message.caption:
    elements.append(Text(" "))

  if message.location:
    elements.append(
      Custom("location", {"lat": message.location.latitude, "lon": message.location.longitude})
    )
  elif message.photo:
    elements.append(Image(f"internal:{PLATFORM}/{me.id}/{message.photo.file_id}"))
  elif message.sticker:
    elements.append(
      Image(f"internal:{PLATFORM}/{me.id}/{message.sticker.file_id}", message.sticker.file_name)
    )
  elif message.voice:
    elements.append(Audio(f"internal:{PLATFORM}/{me.id}/{message.voice.file_id}"))
  elif message.animation:
    elements.append(
      Image(
        f"internal:{PLATFORM}/{me.id}/{message.animation.file_id}", message.animation.file_name
      )
    )
  elif message.video:
    elements.append(
      Video(f"internal:{PLATFORM}/{me.id}/{message.video.file_id}", message.video.file_name)
    )
  elif message.document:
    elements.append(
      File(f"internal:{PLATFORM}/{me.id}/{message.document.file_id}", message.document.file_name)
    )
  elif message.audio:
    elements.append(
      Audio(f"internal:{PLATFORM}/{me.id}/{message.audio.file_id}", message.audio.file_name)
    )

  return elements


def parse_message(me: TGUser, message: Message) -> MessageObject:
  if not message.chat:
    raise ValueError("Message has no chat.")

  guild, channel = parse_guild_channel(me.id, message.chat, message.message_thread_id)
  user = parse_message_sender(me, message)

  return MessageObject.from_elements(
    str(message.id),
    parse_elements(me, message),
    channel,
    guild,
    None,
    user,
    message.date,
    message.edit_date,
  )


def is_my_command(message: Message, user: TGUser) -> bool:
  if not message.text or not message.entities or not user.is_bot:
    return False
  entity = message.entities[0]
  if entity.type != MessageEntityType.BOT_COMMAND or entity.offset != 0:
    return False
  command = message.text[entity.offset : entity.offset + entity.length]
  splited = command.split("@", 1)
  if len(splited) < 2:
    return True
  command, bot = splited
  if bot == user.username:
    return True
  if not user.usernames:
    return False
  for username in user.usernames:
    if (username.editable or username.active) and username.username == bot:
      return True
  return False
