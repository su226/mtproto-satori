# mtproto-satori

A [Satori](https://satori.chat) implementation based on MTProto using [Kurigram](https://github.com/KurimuzonAkuma/kurigram) and [satori-python](https://github.com/RF-Tar-Railt/satori-python).

## Usage

Obtain your `api_id` and `api_hash` at <https://my.telegram.org>.

Create `config.json`. (Do NOT include comments.)

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

## Features

### API
- [x] login.get
- [x] user.get
- [x] user.channel.create
- [x] message.create
- [x] message.get
- [x] message.update

### Event
- [x] message-created
- [x] interaction/button

### Element

#### Standard
- [x] at
- [ ] sharp (Not supported in Telegram)
- [x] emoji
- [x] a
- [x] img
- [x] audio
- [x] video
- [x] file
- [x] b / strong
- [x] i / em
- [x] u / ins
- [x] s / del
- [x] spl
- [x] code
- [ ] sup (Not supported in Telegram)
- [ ] sub (Not supported in Telegram)
- [x] br
- [x] p
- [x] message
- [x] quote
- [x] author
- [x] button

#### Non-standard, but appeared in [@satorijs/adapter-telegram](https://www.npmjs.com/package/@satorijs/adapter-telegram)
- [x] image
- [x] figure
- [x] pre / code-block
- [x] button-group
