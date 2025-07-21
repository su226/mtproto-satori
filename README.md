# mtproto-satori

A [Satori](https://satori.chat) implementation based on MTProto using [Pyrofork](https://github.com/Mayuri-Chan/pyrofork) and [satori-python](https://github.com/RF-Tar-Railt/satori-python).

## Usage

Obtain your `api_id` and `api_hash` at <https://my.telegram.org>.

Create `config.json`.

```jsonc
{
  "host": "127.0.0.1", // Optional, defaults to "127.0.0.1"
  "port": 5140, // Optional, defaults to 5140
  "path": "/satori", // Optional, defaults to ""
  "api_id": 12345, // Required, example value here won't work
  "api_hash": "0123456789abcdef0123456789abcdef", // Required, example value here won't work
  "phone": "", // Either phone or bot_token is required
  "password": "", // Required if your account has 2FA
  "bot_token": "", // Either phone or bot_token is required
  "proxy": { // Optional
    "scheme": "socks5", // "http", "socks4" or "socks5"
    "hostname": "127.0.0.1",
    "port": 1234,
    "username": "username", // Optional
    "password": "password" // Optional
  }
}
```

Install dependencies with `uv sync`.

Start with `uv run mtproto-satori`.
