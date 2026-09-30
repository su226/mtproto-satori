from datetime import datetime, timedelta

from pyrogram.client import Client
from pyrogram.enums import ChatType
from pyrogram.raw.types.input_peer_channel import InputPeerChannel
from pyrogram.raw.types.input_peer_chat import InputPeerChat
from pyrogram.raw.types.input_peer_user import InputPeerUser
from pyrogram.types import Chat, ChatAdministratorRights, ChatMember, ChatPermissions, Reaction
from pyrogram.types import User as TGUser
from pyrogram.utils import zero_datetime
from satori import Channel, ChannelType, EmojiObject, Guild, Member, Role, User

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
  if not member.user:
    raise ValueError("Member has no user.")
  roles = [Role(member.status.name.lower())]
  if not member.permissions or member.permissions.can_send_messages:
    roles.append(Role("can_send_messages"))
  if not member.permissions or member.permissions.can_send_audios:
    roles.append(Role("can_send_audios"))
  if not member.permissions or member.permissions.can_send_documents:
    roles.append(Role("can_send_documents"))
  if not member.permissions or member.permissions.can_send_photos:
    roles.append(Role("can_send_photos"))
  if not member.permissions or member.permissions.can_send_videos:
    roles.append(Role("can_send_videos"))
  if not member.permissions or member.permissions.can_send_video_notes:
    roles.append(Role("can_send_video_notes"))
  if not member.permissions or member.permissions.can_send_voice_notes:
    roles.append(Role("can_send_voice_notes"))
  if not member.permissions or member.permissions.can_send_polls:
    roles.append(Role("can_send_polls"))
  if not member.permissions or member.permissions.can_send_other_messages:
    roles.append(Role("can_send_other_messages"))
  if not member.permissions or member.permissions.can_add_web_page_previews:
    roles.append(Role("can_add_web_page_previews"))
  if not member.permissions or member.permissions.can_react_to_messages:
    roles.append(Role("can_react_to_messages"))
  if not member.permissions or member.permissions.can_edit_tag:
    roles.append(Role("can_edit_tag"))
  if not member.permissions or member.permissions.can_change_info:
    roles.append(Role("can_change_info"))
  if not member.permissions or member.permissions.can_invite_users:
    roles.append(Role("can_invite_users"))
  if not member.permissions or member.permissions.can_pin_messages:
    roles.append(Role("can_pin_messages"))
  if not member.permissions or member.permissions.can_manage_topics:
    roles.append(Role("can_manage_topics"))
  if member.privileges:
    if member.privileges.is_anonymous:
      roles.append(Role("is_anonymous"))
    if member.privileges.can_delete_messages:
      roles.append(Role("can_delete_messages"))
    if member.privileges.can_manage_video_chats:
      roles.append(Role("can_manage_video_chats"))
    if member.privileges.can_restrict_members:
      roles.append(Role("can_restrict_members"))
    if member.privileges.can_promote_members:
      roles.append(Role("can_promote_members"))
    if member.privileges.can_change_info:
      roles.append(Role("can_change_info"))
    if member.privileges.can_invite_users:
      roles.append(Role("can_invite_users"))
    if member.privileges.can_post_stories:
      roles.append(Role("can_post_stories"))
    if member.privileges.can_edit_stories:
      roles.append(Role("can_edit_stories"))
    if member.privileges.can_delete_stories:
      roles.append(Role("can_delete_stories"))
    if member.privileges.can_post_messages:
      roles.append(Role("can_post_messages"))
    if member.privileges.can_edit_messages:
      roles.append(Role("can_edit_messages"))
    if member.privileges.can_pin_messages:
      roles.append(Role("can_pin_messages"))
    if member.privileges.can_manage_topics:
      roles.append(Role("can_manage_topics"))
    if member.privileges.can_manage_direct_messages:
      roles.append(Role("can_manage_direct_messages"))
    if member.privileges.can_manage_tags:
      roles.append(Role("can_manage_tags"))
    if member.privileges.can_send_welcome_messages:
      roles.append(Role("can_send_welcome_messages"))
  return Member(parse_user(self_id, member.user), joined_at=member.joined_date, roles=roles)


def parse_reaction(reaction: Reaction) -> EmojiObject:
  if reaction.emoji:
    return EmojiObject(reaction.emoji)
  if reaction.custom_emoji_id:
    return EmojiObject(reaction.custom_emoji_id)
  if reaction.is_paid:
    return EmojiObject("paid")
  raise ValueError("Invalid reaction.")


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
    parsed_channel_id = int(split_id[0])
    parsed_message_id = int(split_id[1])
  else:
    parsed_channel_id, _ = await resolve_channel_id(client, channel_id)
    parsed_message_id = int(split_id[0])
  return parsed_channel_id, parsed_message_id


async def kick_chat_member(client: Client, chat_id: int, user_id: int) -> None:
  await client.ban_chat_member(chat_id, user_id, datetime.now() + timedelta(minutes=1))
  if chat_id < -1000000000000:
    await client.unban_chat_member(chat_id, user_id)


async def restrict_chat_member(
  client: Client,
  chat_id: int,
  user_id: int,
  until_date: datetime | None = None,
) -> None:
  permissions = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_topics=False,
  )
  await client.restrict_chat_member(chat_id, user_id, permissions, until_date or zero_datetime())


async def unrestrict_chat_member(client: Client, chat_id: int, user_id: int) -> None:
  permissions = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_manage_topics=True,
  )
  await client.restrict_chat_member(chat_id, user_id, permissions)


async def promote_chat_member(client: Client, chat_id: int, user_id: int) -> None:
  # For basic groups, editChatAdmin should be used.
  # But bots cannot use that method.
  await client.promote_chat_member(chat_id, user_id)


async def demote_chat_member(client: Client, chat_id: int, user_id: int) -> None:
  privileges = ChatAdministratorRights(can_manage_chat=False)
  await client.promote_chat_member(chat_id, user_id, privileges)


ADMINISTRATOR_RIGHTS = {
  "is_anonymous",
  "can_delete_messages",
  "can_manage_video_chats",
  "can_restrict_members",
  "can_promote_members",
  "can_change_info",
  "can_invite_users",
  "can_post_stories",
  "can_edit_stories",
  "can_delete_stories",
  "can_post_messages",
  "can_edit_messages",
  "can_pin_messages",
  "can_manage_topics",
  "can_manage_direct_messages",
  "can_manage_tags",
  "can_send_welcome_messages",
}


async def set_administrator_privilege(
  client: Client,
  chat_id: int,
  user_id: int,
  privilege: str,
  toggle: bool,
) -> None:
  if chat_id >= -1000000000000:
    raise ValueError("Fine-grained permissions only available at supergroups or channels.")
  if privilege not in ADMINISTRATOR_RIGHTS:
    raise KeyError("Invalid permission.")
  member = await client.get_chat_member(chat_id, user_id)
  privileges = member.privileges or ChatAdministratorRights(can_manage_chat=False)
  setattr(privileges, privilege, toggle)
  if toggle:
    privileges.can_manage_chat = True
  await client.promote_chat_member(chat_id, user_id, privileges)


RESTRICTIONS = {
  "can_send_messages",
  "can_send_audios",
  "can_send_documents",
  "can_send_photos",
  "can_send_videos",
  "can_send_video_notes",
  "can_send_voice_notes",
  "can_send_polls",
  "can_send_other_messages",
  "can_add_web_page_previews",
  "can_react_to_messages",
  "can_edit_tag",
  "can_change_info",
  "can_invite_users",
  "can_pin_messages",
  "can_manage_topics",
}


async def set_member_permission(
  client: Client,
  chat_id: int,
  user_id: int,
  permission: str,
  toggle: bool,
) -> None:
  if chat_id >= -1000000000000:
    raise ValueError("Fine-grained permissions only available at supergroups or channels.")
  if permission not in RESTRICTIONS:
    raise KeyError("Invalid permission.")
  member = await client.get_chat_member(chat_id, user_id)
  permissions = member.permissions or ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_react_to_messages=True,
    can_edit_tag=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_manage_topics=True,
  )
  setattr(permissions, permission, toggle)
  await client.restrict_chat_member(chat_id, user_id, permissions)
