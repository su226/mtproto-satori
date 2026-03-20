import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast

from launart import Launart
from launart.status import Phase
from pyrogram.client import Client
from pyrogram.enums import ChatType
from pyrogram.file_id import FileId
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
from pyrogram.types import (
  CallbackQuery,
  ChatMember,
  ChatMemberUpdated,
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
  User,
)
from satori.server import Adapter, Request
from satori.server.adapter import LoginType
from satori.server.route import (
  ChannelParam,
  GuildGetParam,
  GuildMemberGetParam,
  GuildXXXListParam,
  MessageOpParam,
  MessageParam,
  MessageUpdateParam,
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
  parse_guild,
  parse_guild_channel,
  parse_member,
  parse_reaction,
  parse_sender_chat,
  parse_user,
  resolve_channel_id,
  resolve_channel_message_id,
  resolve_peer,
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
    if bot_token:
      self.session_name = "bot_" + bot_token.split(":", 1)[0]
    else:
      self.session_name = "user_" + re.sub(r"[+()\s-]", "", phone)
    self.client: Client | None = None
    self.me: Me | None = None
    self.storage = SqliteStorage(self.session_name)
    self.merge_media_groups_receive = merge_media_groups_receive
    self.media_groups = dict[int, tuple[datetime, list[Message]]]()
    self.ignore_automatic_forward_interval = ignore_automatic_forward_interval
    self.ignore_automatic_forward_ids = dict[tuple[int, int], asyncio.Task]()
    self.route(Api.CHANNEL_GET)(self._route_channel_get)
    self.route(Api.GUILD_GET)(self._route_guild_get)
    self.route(Api.GUILD_MEMBER_GET)(self._route_guild_member_get)
    self.route(Api.GUILD_MEMBER_LIST)(self._route_guild_member_list)
    self.route(Api.LOGIN_GET)(self._route_login_get)
    self.route(Api.USER_GET)(self._route_user_get)
    self.route(Api.USER_CHANNEL_CREATE)(self._route_user_channel_create)
    self.route(Api.MESSAGE_CREATE)(self._route_message_create)
    self.route(Api.MESSAGE_GET)(self._route_message_get)
    self.route(Api.MESSAGE_DELETE)(self._route_message_delete)
    self.route(Api.MESSAGE_UPDATE)(self._route_message_update)

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

  async def _route_login_get(self, request: Request[Any]) -> Login:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    me = await self._update_me()
    return me.satori

  async def _route_user_get(self, request: Request[UserOpParam]) -> User:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    user_id = await resolve_peer(self.client, request.params["user_id"])
    if -1000000000000 < user_id < 0:
      raise ValueError(
        "Only supergroups/channels can act like anonymous users, not regular groups."
      )
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

  async def launch(self, manager: Launart) -> None:
    async with self.stage("preparing"):
      self.client = Client(
        self.session_name,
        self.api_id,
        self.api_hash,
        proxy=cast(dict, self.proxy),
        bot_token=self.bot_token,
        phone_number=self.phone,
        password=self.password,
        workdir=Path.cwd(),
      )
      self.client.on_message()(self._on_message)
      self.client.on_edited_message()(self._on_edited_message)
      self.client.on_deleted_messages()(self._on_deleted_messages)
      self.client.on_callback_query()(self._on_callback_query)
      self.client.on_chat_member_updated()(self._on_chat_member_updated)
      self.client.on_message_reaction()(self._on_message_reaction)
      self.client.on_message_reaction_count()(self._on_message_reaction_count)
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
    if not self.me:
      return []
    return [self.me.satori]
