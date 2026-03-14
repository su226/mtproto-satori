from pyrogram.client import Client
from pyrogram.enums import ChatType
from pyrogram.raw.types import InputPeerChannel, InputPeerChat, InputPeerUser
from pyrogram.types import Chat, ChatMember
from pyrogram.types import User as TGUser
from satori import Channel, ChannelType, Guild, Member, Role, User

from mtproto_satori.const import PLATFORM


def parse_user(self_id: int, user: TGUser) -> User:
  return User(
    str(user.id),
    user.username,
    f"{user.first_name} {user.last_name}" if user.last_name else user.first_name,
    f"internal:{PLATFORM}/{self_id}/{user.photo.big_file_id}" if user.photo else None,
    user.is_bot,
  )


def parse_sender_chat(self_id: int, chat: Chat) -> User:
  chat_id = str(chat.id)
  if chat.first_name:
    chat_title = f"{chat.first_name} {chat.last_name}" if chat.last_name else chat.first_name
  elif chat.title:
    chat_title = chat.title
  elif chat.username:
    chat_title = chat.username
  else:
    chat_title = chat_id
  return User(
    chat_id,
    chat.username,
    chat_title,
    f"internal:{PLATFORM}/{self_id}/{chat.photo.big_file_id}" if chat.photo else None,
    False,
  )


def parse_guild(self_id: int, chat: Chat) -> Guild:
  return Guild(
    str(chat.id),
    chat.title,
    f"internal:{PLATFORM}/{self_id}/{chat.photo.big_file_id}" if chat.photo else None,
  )


def parse_guild_channel(
  self_id: int, chat: Chat, thread_id: int | None = None
) -> tuple[Guild | None, Channel]:
  if chat.type in (ChatType.PRIVATE, ChatType.BOT):
    guild = None
    channel = Channel(str(chat.id), ChannelType.DIRECT)
  else:
    guild = parse_guild(self_id, chat)
    channel = Channel(f"{chat.id}:{thread_id}" if thread_id else str(chat.id))
  return guild, channel


def parse_member(self_id: int, member: ChatMember) -> Member:
  return Member(
    parse_user(self_id, member.user),
    joined_at=member.joined_date,
    roles=[Role(id=member.status.name.lower())],
  )


async def resolve_peer(client: Client, guild_id: str) -> int:
  try:
    chat_id = int(guild_id)
  except ValueError:
    peer = await client.resolve_peer(guild_id)
    if isinstance(peer, InputPeerUser):
      chat_id = peer.user_id
    elif isinstance(peer, InputPeerChat):
      chat_id = -peer.chat_id
    elif isinstance(peer, InputPeerChannel):
      chat_id = -(1000000000000 + peer.channel_id)
    else:
      raise ValueError("Cannot resolve peer")
  return chat_id


async def resolve_channel_id(client: Client, channel_id: str) -> tuple[int, int | None]:
  split_id = channel_id.split(":", 1)
  if len(split_id) == 2:
    chat_id = await resolve_peer(client, split_id[0])
    thread_id = int(split_id[1])
  else:
    chat_id = await resolve_peer(client, split_id[0])
    thread_id = None
  return chat_id, thread_id


async def resolve_channel_message_id(
  client: Client,
  channel_id: str,
  message_id: str,
) -> tuple[int, int]:
  split_id = message_id.split(":", 1)
  if len(split_id) == 2:
    channel_id = int(split_id[0])
    message_id = int(split_id[1])
  else:
    channel_id, _ = await resolve_channel_id(client, channel_id)
    message_id = int(split_id[0])
  return channel_id, message_id
