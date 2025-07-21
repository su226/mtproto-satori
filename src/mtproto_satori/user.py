from pyrogram.enums import ChatType
from pyrogram.types import Chat
from pyrogram.types import User as TGUser
from satori.model import Channel, ChannelType, Guild, User

from mtproto_satori.const import PLATFORM


def parse_user(self_id: int, user: TGUser) -> User:
  return User(
    str(user.id),
    user.username,
    f"{user.first_name} {user.last_name}" if user.last_name else user.first_name,
    f"internal:{PLATFORM}/{self_id}/{user.photo.big_file_id}" if user.photo else None,
    user.is_bot,
  )


def parse_guild_channel(
  self_id: int, chat: Chat, thread_id: int | None = None
) -> tuple[Guild | None, Channel]:
  if chat.type in (ChatType.PRIVATE, ChatType.BOT):
    guild = None
    channel = Channel(str(chat.id), ChannelType.DIRECT)
  else:
    guild = Guild(
      str(chat.id),
      chat.title,
      f"internal:{PLATFORM}/{self_id}/{chat.photo.big_file_id}" if chat.photo else None,
    )
    channel = Channel(str(thread_id) if thread_id else str(chat.id))
  return guild, channel
