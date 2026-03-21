import argparse
import tomllib

from satori.server import Server

from mtproto_satori import MTProtoAdapter


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--config", "-c", default="config.toml")
  args = parser.parse_args()
  with open(args.config, "rb") as f:
    config = tomllib.load(f)
  server = Server(
    config.get("host", "127.0.0.1"),
    config.get("port", 5140),
    config.get("path", ""),
    token=config.get("token", ""),
  )
  merge_media_groups = config.get("merge_media_groups", {})
  server.apply(
    MTProtoAdapter(
      config["api_id"],
      config["api_hash"],
      config.get("phone", ""),
      config.get("password", ""),
      config.get("bot_token", ""),
      config.get("test_mode", False),
      config.get("proxy", None),
      merge_media_groups_receive=merge_media_groups.get("receive", 0.1),
      ignore_automatic_forward_interval=config.get("ignore_automatic_forward_interval", 10),
    )
  )
  server.run()


if __name__ == "__main__":
  main()
