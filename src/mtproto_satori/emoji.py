from collections.abc import Iterable
from itertools import chain

from pyrogram.client import Client
from pyrogram.types import Message, Sticker
from satori.parser import Element


def extract_emojis_from_tg_message(message: Message | Iterable[Message]) -> set[int]:
  if isinstance(message, Message):
    return (
      {entity.custom_emoji_id for entity in message.entities if entity.custom_emoji_id}
      if message.entities
      else set()
    )
  return set(chain.from_iterable(extract_emojis_from_tg_message(message) for message in message))


def extract_emojis_from_satori_elements(
  element: Element | Iterable[Element], only_without_name: bool = False
) -> set[int]:
  if isinstance(element, Element):
    if element.type == "emoji":
      emoji_id = element.attrs.get("id")
      if emoji_id and (not only_without_name or not element.attrs.get("name")):
        try:
          return {int(emoji_id)}
        except ValueError:
          pass
      return set()
    element = element.children
  return set(
    chain.from_iterable(
      extract_emojis_from_satori_elements(element, only_without_name) for element in element
    )
  )


async def fetch_emojis(client: Client, emojis: Iterable[int]) -> dict[int, Sticker]:
  emojis = list(emojis)
  return (
    {
      sticker.custom_emoji_id: sticker
      for sticker in await client.get_custom_emoji_stickers(emojis)
      if sticker.custom_emoji_id
    }
    if emojis
    else {}
  )
