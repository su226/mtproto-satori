import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pyrogram.types import Message, Reaction

UPDATE_SCHEMA_1_TO_2 = """
CREATE TABLE reactions(
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  reactions TEXT NOT NULL,
  PRIMARY KEY(chat_id, message_id)
);
"""

SCHEMA = f"""
CREATE TABLE metadata(
  version INTEGER
);

INSERT INTO metadata(version) VALUES (2);

CREATE TABLE messages(
  chat_id INTEGER NOT NULL,
  message_id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  content TEXT NOT NULL
);

CREATE TABLE channel_messages(
  chat_id INTEGER NOT NULL,
  thread_id INTEGER,
  message_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  content TEXT NOT NULL,
  PRIMARY KEY(chat_id, message_id)
);

{UPDATE_SCHEMA_1_TO_2}
"""


@dataclass
class StoredMessage:
  chat_id: int
  thread_id: int | None
  message_id: int
  user_id: int
  content: str

  @classmethod
  def from_message(cls, self_id: int, message: Message, content: str) -> Self:
    if not message.chat:
      raise ValueError("Message has no chat")
    chat_id = message.chat.id
    if not chat_id:
      raise ValueError("Chat has no id")
    if message.sender_chat and message.sender_chat.id:
      user_id = message.sender_chat.id
    elif message.from_user:
      user_id = message.from_user.id
    elif message.outgoing:
      user_id = self_id
    else:
      user_id = chat_id
    return cls(chat_id, message.message_thread_id, message.id, user_id, content)


StoredReactions = dict[str, int]


def serialize_reactions(reactions: list[Reaction]) -> StoredReactions:
  result = StoredReactions()
  for reaction in reactions:
    if reaction.count:
      if reaction.emoji:
        result[reaction.emoji] = reaction.count
      if reaction.custom_emoji_id:
        result[str(reaction.custom_emoji_id)] = reaction.count
      if reaction.is_paid:
        result["paid"] = reaction.count
  return result


class SqliteStorage:
  def __init__(self, session_name: str) -> None:
    self.session_name = session_name

  async def open(self) -> None:
    path = Path(f"storage_{self.session_name}.db")
    path_exists = path.exists()
    self.conn = sqlite3.connect(path)
    if not path_exists:
      with self.conn:
        self.conn.executescript(SCHEMA)
    else:
      await self.__upgrade()

  async def __upgrade(self) -> None:
    (version,) = self.conn.execute("SELECT version FROM metadata").fetchone()
    if version == 1:
      with self.conn:
        self.conn.executescript(UPDATE_SCHEMA_1_TO_2)
        self.conn.execute("UPDATE metadata SET version = 2")

  async def close(self) -> None:
    self.conn.close()

  async def get_channel_message(self, chat_id: int, message_id: int) -> StoredMessage | None:
    result = self.conn.execute(
      """
      SELECT chat_id, thread_id, message_id, user_id, content FROM channel_messages
      WHERE chat_id = ? AND message_id = ?
      """,
      (chat_id, message_id),
    ).fetchone()
    if not result:
      return None
    chat_id, thread_id, message_id, user_id, content = result
    return StoredMessage(chat_id, thread_id, message_id, user_id, content)

  async def get_message(self, message_id: int) -> StoredMessage | None:
    result = self.conn.execute(
      """
      SELECT chat_id, message_id, user_id, content FROM messages
      WHERE message_id = ?
      """,
      (message_id,),
    ).fetchone()
    if not result:
      return None
    chat_id, message_id, user_id, content = result
    return StoredMessage(chat_id, None, message_id, user_id, content)

  async def put_message(self, message: StoredMessage) -> None:
    with self.conn:
      if message.chat_id < -1000000000000:
        try:
          self.conn.execute(
            """
            INSERT INTO channel_messages(chat_id, thread_id, message_id, user_id, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
              message.chat_id,
              message.thread_id,
              message.message_id,
              message.user_id,
              message.content,
            ),
          )
        except sqlite3.IntegrityError:
          self.conn.execute(
            """
            UPDATE channel_messages
            SET thread_id = ?, user_id = ?, content = ?
            WHERE chat_id = ? AND message_id = ?
            """,
            (
              message.thread_id,
              message.user_id,
              message.content,
              message.chat_id,
              message.message_id,
            ),
          )
      else:
        try:
          self.conn.execute(
            """
            INSERT INTO messages(chat_id, message_id, user_id, content)
            VALUES (?, ?, ?, ?)
            """,
            (message.chat_id, message.message_id, message.user_id, message.content),
          )
        except sqlite3.IntegrityError:
          self.conn.execute(
            """
            UPDATE messages
            SET chat_id = ?, user_id = ?, content = ?
            WHERE message_id = ?
            """,
            (message.chat_id, message.user_id, message.content, message.message_id),
          )

  async def del_message(self, message: StoredMessage) -> None:
    with self.conn:
      if message.chat_id < -1000000000000:
        self.conn.execute(
          """
          DELETE FROM channel_messages
          WHERE chat_id = ? AND message_id = ?
          """,
          (message.chat_id, message.message_id),
        )
      else:
        self.conn.execute(
          """
          DELETE FROM messages
          WHERE message_id = ?
          """,
          (message.message_id,),
        )

  async def get_reactions(self, chat_id: int, message_id: int) -> StoredReactions:
    result = self.conn.execute(
      "SELECT reactions FROM reactions WHERE chat_id = ? AND message_id = ?",
      (chat_id, message_id),
    ).fetchone()
    if not result:
      return {}
    return json.loads(result[0])

  async def put_reactions(self, chat_id: int, message_id: int, reactions: StoredReactions) -> None:
    reactions_json = json.dumps(reactions, separators=(",", ":"))
    with self.conn:
      try:
        self.conn.execute(
          "INSERT INTO reactions(chat_id, message_id, reactions) VALUES (?, ?, ?)",
          (chat_id, message_id, reactions_json),
        )
      except sqlite3.IntegrityError:
        self.conn.execute(
          "UPDATE reactions SET reactions = ? WHERE chat_id = ? AND message_id = ?",
          (reactions_json, chat_id, message_id),
        )
