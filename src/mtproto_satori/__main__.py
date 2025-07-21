from satori.server import Server
import json

from mtproto_satori import MTProtoAdapter


def main() -> None:
  with open("config.json") as f:
    config = json.load(f)
  server = Server(
    config.get("host", "127.0.0.1"),
    config.get("port", 5140),
    config.get("path", ""),
    token=config.get("token", ""),
  )
  server.apply(MTProtoAdapter(
    "session",
    config["api_id"],
    config["api_hash"],
    config.get("phone", ""),
    config.get("password", ""),
    config.get("bot_token", ""),
    config.get("proxy", None),
  ))
  server.run()


if __name__ == "__main__":
  main()
