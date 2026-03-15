import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pyrogram.types import Message

SCHEMA = """
CREATE TABLE metadata(
  version INTEGER
);

INSERT INTO metadata(version) VALUES (1);

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

  async def close(self) -> None:
    self.conn.close()

  async def get_channel_message(self, chat_id: int, message_id: int) -> StoredMessage:
    result = self.conn.execute(
      """
      SELECT chat_id, thread_id, message_id, user_id, content FROM channel_messages
      WHERE chat_id = ? AND message_id = ?
      """,
      (chat_id, message_id),
    ).fetchone()
    if not result:
      raise KeyError("Message not stored")
    chat_id, thread_id, message_id, user_id, content = result
    return StoredMessage(chat_id, thread_id, message_id, user_id, content)

  async def get_message(self, message_id: int) -> StoredMessage:
    result = self.conn.execute(
      """
      SELECT chat_id, message_id, user_id, content FROM messages
      WHERE message_id = ?
      """,
      (message_id,),
    ).fetchone()
    if not result:
      raise KeyError("Message not stored")
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
