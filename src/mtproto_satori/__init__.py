import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast

from launart import Launart
from launart.status import Phase
from pyrogram.client import Client
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.file_id import FileId
from pyrogram.raw.base.chat import Chat as RawChat
from pyrogram.raw.base.update import Update as RawUpdate
from pyrogram.raw.base.user import User as RawUser
from pyrogram.raw.functions.channels.get_participants import GetParticipants
from pyrogram.raw.functions.messages.get_full_chat import GetFullChat
from pyrogram.raw.types.channel_full import ChannelFull
from pyrogram.raw.types.channel_participants_search import ChannelParticipantsSearch
from pyrogram.raw.types.channels.channel_participants_not_modified import (
  ChannelParticipantsNotModified,
)
from pyrogram.raw.types.chat_participants_forbidden import ChatParticipantsForbidden
from pyrogram.raw.types.input_channel import InputChannel
from pyrogram.raw.types.input_peer_channel import InputPeerChannel
from pyrogram.raw.types.input_peer_chat import InputPeerChat
from pyrogram.raw.types.update_user import UpdateUser
from pyrogram.raw.types.update_user_name import UpdateUserName
from pyrogram.session.session import Session
from pyrogram.types import (
  CallbackQuery,
  ChatJoinRequest,
  ChatMember,
  ChatMemberUpdated,
  ChatPermissions,
  Message,
  MessageOriginChannel,
  MessageReactionCountUpdated,
  MessageReactionUpdated,
)
from pyrogram.types import User as TGUser
from satori import (
  Api,
  ButtonInteraction,
  Channel,
  ChannelType,
  EmojiObject,
  Event,
  EventType,
  Guild,
  Login,
  LoginStatus,
  Member,
  MessageObject,
  PageResult,
  Role,
  User,
)
from satori.server import Adapter, Request
from satori.server.adapter import LoginType
from satori.server.route import (
  ApproveParam,
  ChannelCreateParam,
  ChannelMuteParam,
  ChannelParam,
  ChannelUpdateParam,
  GuildGetParam,
  GuildMemberGetParam,
  GuildMemberKickParam,
  GuildMemberMuteParam,
  GuildMemberRoleParam,
  GuildXXXListParam,
  MessageOpParam,
  MessageParam,
  MessageUpdateParam,
  ReactionCreateParam,
  ReactionDeleteParam,
  UserChannelCreateParam,
  UserOpParam,
)
from starlette.responses import Response, StreamingResponse

from mtproto_satori.const import ADAPTER, PLATFORM
from mtproto_satori.message_receive import is_my_command, parse_elements, parse_message
from mtproto_satori.message_send import send_message, update_message
from mtproto_satori.storage import (
  SqliteStorage,
  StoredMessage,
  StoredReactions,
  serialize_reactions,
)
from mtproto_satori.user import (
  demote_chat_member,
  kick_chat_member,
  parse_guild,
  parse_guild_channel,
  parse_member,
  parse_reaction,
  parse_sender_chat,
  parse_user,
  promote_chat_member,
  resolve_channel_id,
  resolve_channel_message_id,
  resolve_peer,
  restrict_chat_member,
  unrestrict_chat_member,
)


class Proxy(TypedDict):
  scheme: Literal["socks5", "socks4", "http"]
  hostname: str
  port: int
  username: NotRequired[str]
  password: NotRequired[str]


@dataclass
class Me:
  tg: TGUser
  satori: Login


class MTProtoAdapter(Adapter):
  def __init__(
    self,
    api_id: int,
    api_hash: str,
    phone: str = "",
    password: str = "",
    bot_token: str = "",
    test_mode: bool = False,
    proxy: Proxy | None = None,
    *,
    ignore_automatic_forward_interval: float = 10,
    merge_media_groups_receive: float = 0.1,
  ):
    super().__init__()
    self.queue = asyncio.Queue[Event]()
    self.api_id = api_id
    self.api_hash = api_hash
    self.proxy = proxy
    self.phone = phone
    self.password = password
    self.bot_token = bot_token
    self.test_mode = test_mode
    if bot_token:
      self.session_name = "bot_" + bot_token.split(":", 1)[0]
    else:
      self.session_name = "user_" + re.sub(r"[+()\s-]", "", phone)
    if test_mode:
      self.session_name = "test_" + self.session_name
    self.client: Client | None = None
    self.me: Me | None = None
    self.storage = SqliteStorage(self.session_name)
    self.is_connected = False
    self.merge_media_groups_receive = merge_media_groups_receive
    self.media_groups = dict[int, tuple[datetime, list[Message]]]()
    self.ignore_automatic_forward_interval = ignore_automatic_forward_interval
    self.ignore_automatic_forward_ids = dict[tuple[int, int], asyncio.Task]()
    self.route(Api.CHANNEL_GET)(self._route_channel_get)
    self.route(Api.CHANNEL_CREATE)(self._route_channel_create)
    self.route(Api.CHANNEL_UPDATE)(self._route_channel_update)
    self.route(Api.CHANNEL_DELETE)(self._route_channel_delete)
    self.route(Api.CHANNEL_MUTE)(self._route_channel_mute)
    self.route(Api.GUILD_GET)(self._route_guild_get)
    self.route(Api.GUILD_MEMBER_GET)(self._route_guild_member_get)
    self.route(Api.GUILD_MEMBER_LIST)(self._route_guild_member_list)
    self.route(Api.GUILD_MEMBER_KICK)(self._route_guild_member_kick)
    self.route(Api.GUILD_MEMBER_MUTE)(self._route_guild_member_mute)
    self.route(Api.GUILD_MEMBER_APPROVE)(self._route_guild_member_approve)
    self.route(Api.GUILD_MEMBER_ROLE_SET)(self._route_guild_member_role_set)
    self.route(Api.GUILD_MEMBER_ROLE_UNSET)(self._route_guild_member_role_unset)
    self.route(Api.GUILD_ROLE_LIST)(self._route_guild_role_list)
    self.route(Api.LOGIN_GET)(self._route_login_get)
    self.route(Api.USER_GET)(self._route_user_get)
    self.route(Api.USER_CHANNEL_CREATE)(self._route_user_channel_create)
    self.route(Api.MESSAGE_CREATE)(self._route_message_create)
    self.route(Api.MESSAGE_GET)(self._route_message_get)
    self.route(Api.MESSAGE_DELETE)(self._route_message_delete)
    self.route(Api.MESSAGE_UPDATE)(self._route_message_update)
    self.route(Api.REACTION_CREATE)(self._route_reaction_create)
    self.route(Api.REACTION_DELETE)(self._route_reaction_delete)

  @property
  def required(self) -> set[str]:
    return {"satori-python.server"}

  @property
  def stages(self) -> set[Phase]:
    return {"preparing", "blocking", "cleanup"}

  async def remove_ignore_automatic_forward(self, channel_id: int, message_id: int) -> None:
    await asyncio.sleep(self.ignore_automatic_forward_interval)
    del self.ignore_automatic_forward_ids[channel_id, message_id]

  async def _on_message(self, client: Client, message: Message) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    if self.merge_media_groups_receive > 0 and message.media_group_id:
      if message.media_group_id in self.media_groups:
        _, messages = self.media_groups[message.media_group_id]
      else:
        messages = []
      now = datetime.now()
      messages.append(message)
      self.media_groups[message.media_group_id] = (now, messages)
      await asyncio.sleep(self.merge_media_groups_receive)
      time, _ = self.media_groups[message.media_group_id]
      if time != now:
        return
      del self.media_groups[message.media_group_id]
      messages.sort(key=lambda update: update.id)
      message = messages[0]
      parsed = parse_message(self.me.tg, message)
      await self.storage.put_message(
        StoredMessage.from_message(self.me.tg.id, message, parsed.content)
      )
      for add_message in messages[1:]:
        add_content = "".join(str(element) for element in parse_elements(self.me.tg, add_message))
        parsed.content += add_content
        await self.storage.put_message(
          StoredMessage.from_message(self.me.tg.id, add_message, add_content)
        )
    else:
      parsed = parse_message(self.me.tg, message)
      await self.storage.put_message(
        StoredMessage.from_message(self.me.tg.id, message, parsed.content)
      )
    if self.ignore_automatic_forward_interval > 0 and message.chat and message.chat.id:
      if message.chat.type == ChatType.CHANNEL:
        self.ignore_automatic_forward_ids[message.chat.id, message.id] = asyncio.create_task(
          self.remove_ignore_automatic_forward(message.chat.id, message.id)
        )
      elif (
        message.automatic_forward
        and isinstance(message.forward_origin, MessageOriginChannel)
        and (message.forward_origin.chat.id, message.forward_origin.message_id)
        in self.ignore_automatic_forward_ids
      ):
        return
    if not message.date:
      raise ValueError("Message has no date.")
    event = Event(
      EventType.INTERACTION_COMMAND
      if is_my_command(message, self.me.tg)
      else EventType.MESSAGE_CREATED,
      message.date,
      self.me.satori,
      channel=parsed.channel,
      guild=parsed.guild,
      message=parsed,
      user=parsed.user,
    )
    await self.queue.put(event)

  async def _on_edited_message(self, client: Client, message: Message) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    parsed = parse_message(self.me.tg, message)
    if message.chat and message.chat.id and message.chat.id < -1000000000000:
      before = await self.storage.get_channel_message(message.chat.id, message.id)
    else:
      before = await self.storage.get_message(message.id)
    if before and parsed.content == before.content:
      # Message content unchanged, maybe something else changed like reactions?
      return
    await self.storage.put_message(
      StoredMessage.from_message(self.me.tg.id, message, parsed.content)
    )
    if not message.edit_date:
      raise ValueError("Message has no date.")
    event = Event(
      EventType.MESSAGE_UPDATED,
      message.edit_date,
      self.me.satori,
      channel=parsed.channel,
      guild=parsed.guild,
      message=parsed,
      user=parsed.user,
    )
    await self.queue.put(event)

  async def _on_deleted_messages(self, client: Client, messages: list[Message]) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    now = datetime.now()
    for message in messages:
      if message.chat and message.chat.id:
        stored = await self.storage.get_channel_message(message.chat.id, message.id)
      else:
        stored = await self.storage.get_message(message.id)
      if not stored:
        continue
      event = Event(
        EventType.MESSAGE_DELETED,
        now,
        self.me.satori,
        channel=Channel(
          f"{stored.chat_id}:{stored.thread_id}" if stored.thread_id else str(stored.chat_id),
          ChannelType.TEXT if stored.chat_id < 0 else ChannelType.DIRECT,
        ),
        guild=Guild(str(stored.chat_id)) if stored.chat_id < 0 else None,
        message=MessageObject(str(stored.message_id)),
        user=User(str(stored.user_id)),
      )
      await self.queue.put(event)
      await self.storage.del_message(stored)

  async def _on_callback_query(self, client: Client, callback: CallbackQuery) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    message = parse_message(self.me.tg, callback.message)
    event = Event(
      EventType.INTERACTION_BUTTON,
      datetime.now(),
      self.me.satori,
      button=ButtonInteraction(
        callback.data.decode(errors="replace")
        if isinstance(callback.data, bytes)
        else callback.data
      ),
      channel=message.channel,
      guild=message.guild,
      message=message,
      user=parse_user(self.me.tg.id, callback.from_user),
    )
    await self.queue.put(event)
    await callback.answer()

  async def _on_chat_join_request(self, client: Client, request: ChatJoinRequest) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    guild = parse_guild(self.me.tg.id, request.chat)
    user = parse_user(self.me.tg.id, request.from_user)
    event = Event(
      EventType.GUILD_MEMBER_REQUEST,
      request.date,
      self.me.satori,
      guild=guild,
      member=Member(user),
      user=user,
      message=MessageObject(f"guild_member_request:{guild.id}:{user.id}"),
    )
    await self.queue.put(event)

  async def _on_chat_member_updated(self, client: Client, update: ChatMemberUpdated) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    if update.old_chat_member and update.new_chat_member:
      guild = parse_guild(self.me.tg.id, update.chat)
      member = parse_member(self.me.tg.id, update.new_chat_member)
      operator = parse_user(self.me.tg.id, update.from_user)
      event = Event(
        EventType.GUILD_MEMBER_UPDATED,
        update.date,
        self.me.satori,
        guild=guild,
        member=member,
        user=member.user,
        operator=operator,
      )
      await self.queue.put(event)
    elif update.old_chat_member:
      guild = parse_guild(self.me.tg.id, update.chat)
      member = parse_member(self.me.tg.id, update.old_chat_member)
      operator = parse_user(self.me.tg.id, update.from_user)
      event = Event(
        EventType.GUILD_MEMBER_REMOVED,
        update.date,
        self.me.satori,
        guild=guild,
        member=member,
        user=member.user,
        operator=operator,
      )
      await self.queue.put(event)
    elif update.new_chat_member:
      guild = parse_guild(self.me.tg.id, update.chat)
      member = parse_member(self.me.tg.id, update.new_chat_member)
      operator = parse_user(self.me.tg.id, update.from_user)
      event = Event(
        EventType.GUILD_MEMBER_ADDED,
        update.date,
        self.me.satori,
        guild=guild,
        member=member,
        user=member.user,
        operator=operator,
      )
      await self.queue.put(event)

  async def _on_message_reaction(self, client: Client, reaction: MessageReactionUpdated) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    guild, channel = parse_guild_channel(self.me.tg.id, reaction.chat)
    if reaction.actor_chat:
      user = parse_sender_chat(self.me.tg.id, reaction.actor_chat)
    elif reaction.user:
      user = parse_user(self.me.tg.id, reaction.user)
    else:
      user = None
    for emoji in reaction.old_reaction:
      event = Event(
        EventType.REACTION_REMOVED,
        reaction.date,
        self.me.satori,
        channel=channel,
        guild=guild,
        message=MessageObject(id=str(reaction.message_id)),
        user=user,
        emoji=parse_reaction(emoji),
      )
      await self.queue.put(event)
    for emoji in reaction.new_reaction:
      event = Event(
        EventType.REACTION_ADDED,
        reaction.date,
        self.me.satori,
        channel=channel,
        guild=guild,
        message=MessageObject(id=str(reaction.message_id)),
        user=user,
        emoji=parse_reaction(emoji),
      )
      await self.queue.put(event)

  async def _on_message_reaction_count(
    self,
    client: Client,
    reaction: MessageReactionCountUpdated,
  ) -> None:
    if not self.me:
      raise ValueError("Client is not fully initalized.")
    if not reaction.chat.id:
      raise ValueError("Reaction has no chat id.")
    guild, channel = parse_guild_channel(self.me.tg.id, reaction.chat)
    reactions = serialize_reactions(reaction.reactions)
    old_reactions = await self.storage.get_reactions(reaction.chat.id, reaction.message_id)
    await self.storage.put_reactions(reaction.chat.id, reaction.message_id, reactions)
    diff = StoredReactions()
    for id, count in reactions.items():
      diff[id] = count - old_reactions.get(id, 0)
    for id, old_count in old_reactions.items():
      diff[id] = reactions.get(id, 0) - old_count
    for id, diff in diff.items():
      if diff > 0:
        for _ in range(diff):
          event = Event(
            EventType.REACTION_ADDED,
            reaction.date,
            self.me.satori,
            channel=channel,
            guild=guild,
            message=MessageObject(id=str(reaction.message_id)),
            emoji=EmojiObject(id=id),
          )
          await self.queue.put(event)
      elif diff < 0:
        for _ in range(-diff):
          event = Event(
            EventType.REACTION_REMOVED,
            reaction.date,
            self.me.satori,
            channel=channel,
            guild=guild,
            message=MessageObject(id=str(reaction.message_id)),
            emoji=EmojiObject(id=id),
          )
          await self.queue.put(event)

  async def _on_connect(self, client: Client, session: Session) -> None:
    if self.is_connected:
      return
    self.is_connected = True
    if not self.me:
      return
    event = Event(EventType.LOGIN_ADDED, datetime.now(), self.me.satori)
    await self.queue.put(event)

  async def _on_disconnect(self, client: Client, session: Session) -> None:
    # on_disconnected will be called when connection refused.
    if not self.is_connected:
      return
    self.is_connected = False
    if not self.me:
      return
    event = Event(EventType.LOGIN_REMOVED, datetime.now(), self.me.satori)
    await self.queue.put(event)

  def _filter_me_update(self, client: Client, update: RawUpdate) -> bool:
    # UpdateUser: avatar update
    # UpdateUserName: name or nick update
    if not self.me or not isinstance(update, (UpdateUser, UpdateUserName)):
      return False
    return update.user_id == self.me.tg.id

  async def _on_me_update(
    self,
    client: Client,
    update: UpdateUser | UpdateUserName,
    users: dict[int, RawUser],
    chats: dict[int, RawChat],
  ) -> None:
    now = datetime.now()
    me = await self._update_me()
    event = Event(EventType.LOGIN_UPDATED, now, me.satori)
    await self.queue.put(event)

  async def _route_channel_get(self, request: Request[ChannelParam]) -> Channel:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id, thread_id = await resolve_channel_id(self.client, request.params["channel_id"])
    if chat_id > 0:
      channel_id = str(chat_id)
      channel_type = ChannelType.DIRECT
    elif thread_id:
      channel_id = f"{chat_id}:{thread_id}"
      channel_type = ChannelType.TEXT
    else:
      channel_id = str(chat_id)
      channel_type = ChannelType.TEXT
    return Channel(channel_id, channel_type)

  async def _route_channel_create(self, request: Request[ChannelCreateParam]) -> Channel:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    topic = await self.client.create_forum_topic(chat_id, request.params["data"].get("name", ""))
    return Channel(f"{chat_id}:{topic.id}", ChannelType.TEXT, topic.title)

  async def _route_channel_update(self, request: Request[ChannelUpdateParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id, thread_id = await resolve_channel_id(self.client, request.params["channel_id"])
    if not thread_id:
      raise ValueError("Not a forum topic.")
    title = request.params["data"].get("name", "")
    await self.client.edit_forum_topic(chat_id, thread_id, title)

  async def _route_channel_delete(self, request: Request[ChannelParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id, thread_id = await resolve_channel_id(self.client, request.params["channel_id"])
    if not thread_id:
      raise ValueError("Not a forum topic.")
    await self.client.delete_forum_topic(chat_id, thread_id)

  async def _route_channel_mute(self, request: Request[ChannelMuteParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id, thread_id = await resolve_channel_id(self.client, request.params["channel_id"])
    muted = request.params["duration"] > 0
    if thread_id:
      await self.client.edit_forum_topic(chat_id, thread_id, closed=muted)
    else:
      permissions = ChatPermissions(
        can_send_messages=not muted,
        can_send_audios=not muted,
        can_send_documents=not muted,
        can_send_photos=not muted,
        can_send_videos=not muted,
        can_send_video_notes=not muted,
        can_send_voice_notes=not muted,
        can_send_polls=not muted,
        can_send_other_messages=not muted,
        can_add_web_page_previews=not muted,
      )
      await self.client.set_chat_permissions(chat_id, permissions)

  async def _route_guild_get(self, request: Request[GuildGetParam]) -> Guild:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    if chat_id > 0:
      raise ValueError("Direct messages have no guild")
    chat = await self.client.get_chat(chat_id)
    return parse_guild(self.me.tg.id, chat)

  async def _route_guild_member_get(self, request: Request[GuildMemberGetParam]) -> Member:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    user_id = await resolve_peer(self.client, request.params["user_id"])
    member = await self.client.get_chat_member(chat_id, user_id)
    return parse_member(self.me.tg.id, member)

  async def _route_guild_member_list(
    self,
    request: Request[GuildXXXListParam],
  ) -> PageResult[Member]:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    peer_id = request.params["guild_id"]
    try:
      peer_id = int(peer_id)
    except ValueError:
      pass
    # Not using our resolve_peer since we need access hash...
    peer = await self.client.resolve_peer(peer_id)
    if isinstance(peer, InputPeerChannel):
      # Pyrogram doesn't provide offset parameter, use raw API instead.
      offset = int(request.params.get("next", 0))
      r = await self.client.invoke(
        GetParticipants(
          channel=InputChannel(channel_id=peer.channel_id, access_hash=peer.access_hash),
          filter=ChannelParticipantsSearch(q=""),
          offset=offset,
          limit=200,
          hash=0,
        ),
        sleep_threshold=60,
      )
      if isinstance(r, ChannelParticipantsNotModified):
        raise TypeError("Telegram returned ChannelParticipantsNotModified even if hash is 0.")

      members = r.participants
      users = {u.id: u for u in r.users}
      chats = {c.id: c for c in r.chats}

      return PageResult(
        [
          parse_member(self.me.tg.id, ChatMember._parse(self.client, member, users, chats))
          for member in members
        ],
        str(offset + len(members)) if members else None,
      )
    elif isinstance(peer, InputPeerChat):
      r = await self.client.invoke(GetFullChat(chat_id=peer.chat_id))
      if isinstance(r.full_chat, ChannelFull):
        raise TypeError("Telegram returned ChannelFull even if peer is a group.")
      if isinstance(r.full_chat.participants, ChatParticipantsForbidden):
        raise ValueError("Get participants of this group is forbidden.")

      members = r.full_chat.participants.participants
      users = {i.id: i for i in r.users}
      chats = {}

      return PageResult(
        [
          parse_member(self.me.tg.id, ChatMember._parse(self.client, member, users, chats))
          for member in members
        ]
      )
    else:
      raise ValueError("Not a group or channel.")

  async def _route_guild_member_kick(self, request: Request[GuildMemberKickParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    user_id = await resolve_peer(self.client, request.params["user_id"])
    if user_id == self.me.tg.id:
      await self.client.leave_chat(chat_id)
      return
    if request.params.get("permanent", False):
      await self.client.ban_chat_member(chat_id, user_id)
      return
    await kick_chat_member(self.client, chat_id, user_id)

  async def _route_guild_member_mute(self, request: Request[GuildMemberMuteParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    user_id = await resolve_peer(self.client, request.params["user_id"])
    duration = request.params["duration"]
    if duration > 0:
      # Less than 30s will be considered as permanent.
      # A minimum of 60s is used here to account for network fluctuations.
      until_date = datetime.now() + timedelta(milliseconds=max(60_000, duration))
      await restrict_chat_member(self.client, chat_id, user_id, until_date)
    else:
      await unrestrict_chat_member(self.client, chat_id, user_id)

  async def _route_guild_member_approve(self, request: Request[ApproveParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    split_id = request.params["message_id"].removeprefix("guild_member_request:").split(":", 1)
    chat_id = await resolve_peer(self.client, split_id[0])
    user_id = await resolve_peer(self.client, split_id[1])
    if request.params["approve"]:
      await self.client.approve_chat_join_request(chat_id, user_id)
    else:
      await self.client.decline_chat_join_request(chat_id, user_id)

  async def _route_guild_member_role_set(self, request: Request[GuildMemberRoleParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    user_id = await resolve_peer(self.client, request.params["user_id"])
    role_id = request.params["role_id"]
    if role_id == ChatMemberStatus.OWNER.name.lower():
      # transfer_chat_ownership is not usable by bots.
      raise ValueError('"owner" role cannot be set.')
    elif role_id == ChatMemberStatus.ADMINISTRATOR.name.lower():
      await promote_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.MEMBER.name.lower():
      member = await self.client.get_chat_member(chat_id, user_id)
      if member.status == ChatMemberStatus.OWNER:
        raise ValueError('Changing from "owner" to "member" is not feasible.')
      elif member.status == ChatMemberStatus.ADMINISTRATOR:
        await demote_chat_member(self.client, chat_id, user_id)
      elif member.status == ChatMemberStatus.BANNED:
        raise ValueError('Changing from "banned" to "member" is not feasible.')
      elif member.status == ChatMemberStatus.LEFT:
        raise ValueError('Changing from "left" to "member" is not feasible.')
      elif member.status == ChatMemberStatus.RESTRICTED:
        await unrestrict_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.RESTRICTED.name.lower():
      await restrict_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.LEFT.name.lower():
      if user_id == self.me.tg.id:
        await self.client.leave_chat(chat_id)
      else:
        await kick_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.BANNED.name.lower():
      await self.client.ban_chat_member(chat_id, user_id)
    else:
      raise ValueError("Invalid role.")

  async def _route_guild_member_role_unset(self, request: Request[GuildMemberRoleParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    user_id = await resolve_peer(self.client, request.params["user_id"])
    role_id = request.params["role_id"]
    if role_id == ChatMemberStatus.OWNER.name.lower():
      raise ValueError('"owner" role cannot be unset.')
    elif role_id == ChatMemberStatus.ADMINISTRATOR.name.lower():
      await demote_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.MEMBER.name.lower():
      if user_id == self.me.tg.id:
        await self.client.leave_chat(chat_id)
      else:
        await kick_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.RESTRICTED.name.lower():
      await unrestrict_chat_member(self.client, chat_id, user_id)
    elif role_id == ChatMemberStatus.LEFT.name.lower():
      raise ValueError('"left" role cannot be unset.')
    elif role_id == ChatMemberStatus.BANNED.name.lower():
      await self.client.unban_chat_member(chat_id, user_id)
    else:
      raise ValueError("Invalid role.")

  async def _route_guild_role_list(self, request: Request[GuildXXXListParam]) -> PageResult[Role]:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id = await resolve_peer(self.client, request.params["guild_id"])
    if chat_id < -1000000000000:
      return PageResult(
        [
          Role(ChatMemberStatus.OWNER.name.lower()),
          Role(ChatMemberStatus.ADMINISTRATOR.name.lower()),
          Role(ChatMemberStatus.MEMBER.name.lower()),
          Role(ChatMemberStatus.RESTRICTED.name.lower()),
          Role(ChatMemberStatus.LEFT.name.lower()),
          Role(ChatMemberStatus.BANNED.name.lower()),
        ]
      )
    if chat_id < 0:
      return PageResult(
        [
          Role(ChatMemberStatus.OWNER.name.lower()),
          Role(ChatMemberStatus.ADMINISTRATOR.name.lower()),
          Role(ChatMemberStatus.MEMBER.name.lower()),
        ]
      )
    raise ValueError("Not a group.")

  async def _route_login_get(self, request: Request[Any]) -> Login:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    return self.me.satori

  async def _route_user_get(self, request: Request[UserOpParam]) -> User:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    user_id = await resolve_peer(self.client, request.params["user_id"])
    if -1000000000000 < user_id < 0:
      raise ValueError("Only supergroups/channels can act like anonymous users, not basic groups.")
    chat = await self.client.get_chat(user_id)
    return parse_sender_chat(self.me.tg.id, chat)

  async def _route_user_channel_create(self, request: Request[UserChannelCreateParam]) -> Channel:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    user_id = await resolve_peer(self.client, request.params["user_id"])
    if user_id < 0:
      raise ValueError("Not a user")
    return Channel(str(user_id), ChannelType.DIRECT)

  async def _route_message_create(self, request: Request[MessageParam]) -> list[MessageObject]:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    channel_id, thread_id = await resolve_channel_id(self.client, request.params["channel_id"])
    messages = await send_message(
      self.client,
      self.me.tg,
      channel_id,
      thread_id,
      request.params["content"],
    )
    for tg, satori in messages:
      await self.storage.put_message(StoredMessage.from_message(self.me.tg.id, tg, satori.content))
    return [satori for _, satori in messages]

  async def _route_message_get(self, request: Request[MessageOpParam]) -> MessageObject:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    channel_id, message_id = await resolve_channel_message_id(
      self.client,
      request.params["channel_id"],
      request.params["message_id"],
    )
    message = await self.client.get_messages(channel_id, message_id)
    if not message:
      raise ValueError("Message not exist.")
    return parse_message(self.me.tg, message)

  async def _route_message_delete(self, request: Request[MessageOpParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    channel_id, message_id = await resolve_channel_message_id(
      self.client,
      request.params["channel_id"],
      request.params["message_id"],
    )
    count = await self.client.delete_messages(channel_id, message_id)
    if not count:
      raise ValueError("Message not exist.")

  async def _route_message_update(self, request: Request[MessageUpdateParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    channel_id, message_id = await resolve_channel_message_id(
      self.client,
      request.params["channel_id"],
      request.params["message_id"],
    )
    tg, satori = await update_message(
      self.client,
      self.me.tg,
      channel_id,
      message_id,
      request.params["content"],
    )
    await self.storage.put_message(StoredMessage.from_message(self.me.tg.id, tg, satori.content))

  async def _route_reaction_create(self, request: Request[ReactionCreateParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    chat_id, message_id = await resolve_channel_message_id(
      self.client,
      request.params["channel_id"],
      request.params["message_id"],
    )
    emoji_id = request.params["emoji_id"]
    if emoji_id.startswith("paid"):
      try:
        amount = int(emoji_id[4:])
      except ValueError:
        amount = 1
      await self.client.send_paid_reaction(chat_id, message_id, amount)
      return
    try:
      emoji_id = int(emoji_id)
    except ValueError:
      pass
    await self.client.send_reaction(chat_id, message_id, emoji_id)

  async def _route_reaction_delete(self, request: Request[ReactionDeleteParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    if request.params["emoji_id"].startswith("paid"):
      raise ValueError("Cannot retract paid reaction.")
    if user_id := request.params.get("user_id"):
      if await resolve_peer(self.client, user_id) != self.me.tg.id:
        raise ValueError("Cannot retract other's reaction.")
    chat_id, message_id = await resolve_channel_message_id(
      self.client,
      request.params["channel_id"],
      request.params["message_id"],
    )
    await self.client.send_reaction(chat_id, message_id)

  async def launch(self, manager: Launart) -> None:
    async with self.stage("preparing"):
      self.client = Client(
        self.session_name,
        self.api_id,
        self.api_hash,
        proxy=cast(dict, self.proxy),
        test_mode=self.test_mode,
        bot_token=self.bot_token,
        phone_number=self.phone,
        password=self.password,
        workdir=Path.cwd(),
      )
      self.client.on_message()(self._on_message)
      self.client.on_edited_message()(self._on_edited_message)
      self.client.on_deleted_messages()(self._on_deleted_messages)
      self.client.on_callback_query()(self._on_callback_query)
      self.client.on_chat_join_request()(self._on_chat_join_request)
      self.client.on_chat_member_updated()(self._on_chat_member_updated)
      self.client.on_message_reaction()(self._on_message_reaction)
      self.client.on_message_reaction_count()(self._on_message_reaction_count)
      self.client.on_connect()(self._on_connect)
      self.client.on_disconnect()(self._on_disconnect)
      self.client.on_raw_update(self._filter_me_update)(self._on_me_update)
      await self.storage.open()

    async with self.stage("blocking"):
      await self.client.start()
      me = await self._update_me()
      await self.queue.put(
        Event(
          EventType.LOGIN_ADDED,
          datetime.now(),
          me.satori,
        )
      )
      await manager.status.wait_for_sigexit()

    async with self.stage("cleanup"):
      await self.storage.close()
      self.me = None
      await self.client.stop()
      self.client = None

  def get_platform(self) -> str:
    return PLATFORM

  async def publisher(self) -> AsyncIterator[Event]:
    while True:
      event = await self.queue.get()
      yield event

  def ensure(self, platform: str, self_id: str) -> bool:
    return platform == PLATFORM and bool(self.me and self_id == str(self.me.tg.id))

  async def handle_internal(self, request: Request, path: str) -> Response:
    file_id = FileId.decode(path)
    if not self.client or not file_id:
      return Response("Not found", 404)
    return StreamingResponse(self.client.get_file(file_id))

  async def _update_me(self) -> Me:
    assert self.client
    user = await self.client.get_me()
    self.me = Me(user, Login(0, LoginStatus.ONLINE, ADAPTER, PLATFORM, parse_user(user.id, user)))
    return self.me

  async def get_logins(self) -> list[LoginType]:
    # Not using self.client.is_connected becaust it won't change during on_connected / on_disconnected events.
    if not self.is_connected or not self.me:
      return []
    return [self.me.satori]
