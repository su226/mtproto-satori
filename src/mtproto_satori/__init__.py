import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast
from dataclasses import dataclass

from launart import Launart
from launart.status import Phase
from pyrogram.client import Client
from pyrogram.file_id import FileId
from pyrogram.types import CallbackQuery, Message
from pyrogram.types import User as TGUser
from satori.model import ButtonInteraction, Event, Login, LoginStatus, MessageObject, User
from satori.server import Adapter, Api
from satori.server.model import Request
from satori.server.route import MessageOpParam, MessageParam, MessageUpdateParam, UserGetParam
from starlette.responses import Response, StreamingResponse

from mtproto_satori.const import ADAPTER, PLATFORM
from mtproto_satori.message_receive import parse_message
from mtproto_satori.message_send import send_message, update_message
from mtproto_satori.user import parse_guild_channel, parse_user


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
    name: str,
    api_id: int,
    api_hash: str,
    phone: str = "",
    password: str = "",
    bot_token: str = "",
    proxy: Proxy | None = None,
  ):
    super().__init__()
    self.queue = asyncio.Queue[Event]()
    self.name = name
    self.api_id = api_id
    self.api_hash = api_hash
    self.proxy = proxy
    self.phone = phone
    self.password = password
    self.bot_token = bot_token
    self.client: Client | None = None
    self.me: Me | None = None
    self.route(Api.LOGIN_GET)(self._route_login_get)
    self.route(Api.USER_GET)(self._route_user_get)
    self.route(Api.MESSAGE_CREATE)(self._route_message_create)
    self.route(Api.MESSAGE_GET)(self._route_message_get)
    self.route(Api.MESSAGE_UPDATE)(self._route_message_update)

  @property
  def required(self) -> set[str]:
    return {"satori-python.server"}

  @property
  def stages(self) -> set[Phase]:
    return {"preparing", "blocking", "cleanup"}

  async def _on_message(self, client: Client, message: Message) -> None:
    assert self.me
    guild, channel = parse_guild_channel(self.me.tg.id, message.chat, message.message_thread_id)
    event = Event(
      "message-created",
      message.date,
      self.me.satori,
      channel=channel,
      guild=guild,
      message=parse_message(self.me.tg.id, message),
      user=parse_user(self.me.tg.id, message.from_user),
    )
    await self.queue.put(event)

  async def _on_callback_query(self, client: Client, callback: CallbackQuery) -> None:
    assert self.me
    guild, channel = parse_guild_channel(
      self.me.tg.id,
      callback.message.chat,
      callback.message.message_thread_id,
    )
    event = Event(
      "interaction/button",
      datetime.now(),
      self.me.satori,
      button=ButtonInteraction(cast(str, callback.data)),
      channel=channel,
      guild=guild,
      message=parse_message(self.me.tg.id, callback.message),
      user=parse_user(self.me.tg.id, callback.message.from_user),
    )
    await self.queue.put(event)
    await callback.answer()

  async def _route_login_get(self, request: Request[Any]) -> Login:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    await self._update_me()
    return self.me.satori

  async def _route_user_get(self, request: Request[UserGetParam]) -> User:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    user = cast(TGUser, await self.client.get_users(request.params["user_id"]))
    return parse_user(self.me.tg.id, user)

  async def _route_message_create(self, request: Request[MessageParam]) -> list[MessageObject]:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    return await send_message(
      self.client,
      self.me.tg.id,
      int(request.params["channel_id"]),
      request.params["content"],
    )

  async def _route_message_get(self, request: Request[MessageOpParam]) -> MessageObject:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    message = await self.client.get_messages(
      int(request.params["channel_id"]),
      int(request.params["message_id"]),
    )
    return parse_message(self.me.tg.id, cast(Message, message))

  async def _route_message_update(self, request: Request[MessageUpdateParam]) -> None:
    if not self.client or not self.me:
      raise ValueError("Client not started")
    await update_message(
      self.client,
      int(request.params["channel_id"]),
      int(request.params["message_id"]),
      request.params["content"],
    )

  async def launch(self, manager: Launart) -> None:
    async with self.stage("preparing"):
      self.client = Client(
        self.name,
        self.api_id,
        self.api_hash,
        proxy=cast(dict, self.proxy),
        bot_token=self.bot_token,
        phone_number=self.phone,
        password=self.password,
        workdir=Path.cwd(),
      )
      self.client.on_message()(self._on_message)
      self.client.on_callback_query()(self._on_callback_query)

    async with self.stage("blocking"):
      await self.client.start()
      await self._update_me()
      await manager.status.wait_for_sigexit()

    async with self.stage("cleanup"):
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
    return platform == PLATFORM and bool(self.me) and self_id == str(self.me.tg.id)

  async def handle_internal(self, request: Request, path: str) -> Response:
    file_id = FileId.decode(path)
    if not self.client or not file_id:
      return Response("Not found", 404)
    return StreamingResponse(cast(AsyncIterator[bytes], self.client.get_file(file_id)))

  async def _update_me(self) -> None:
    assert self.client
    user = await self.client.get_me()
    self.me = Me(user, Login(0, LoginStatus.ONLINE, ADAPTER, PLATFORM, parse_user(user.id, user)))

  async def get_logins(self) -> list[Login]:
    if not self.me:
      return []
    return [self.me.satori]
