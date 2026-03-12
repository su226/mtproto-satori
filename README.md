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
  "token": "", // Optional, defaults to ""
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

- [ ] channel.get
- [ ] channel.list
- [ ] channel.create
- [ ] channel.update
- [ ] channel.delete
- [ ] channel.mute
- [ ] friend.list
- [ ] friend.delete
- [ ] friend.approve
- [ ] guild.get
- [ ] guild.list
- [ ] guild.approve
- [ ] guild.member.get
- [ ] guild.member.list
- [ ] guild.member.kick
- [ ] guild.member.mute
- [ ] guild.member.approve
- [ ] guild.member.role.set
- [ ] guild.member.role.unset
- [ ] guild.role.list
- [ ] guild.role.create
- [ ] guild.role.update
- [ ] guild.role.delete
- [x] login.get
- [x] message.create
- [x] message.get
- [x] message.update
- [ ] message.list
- [ ] reaction.create
- [ ] reaction.delete
- [ ] reaction.clear
- [ ] reaction.list
- [x] user.channel.create
- [x] user.get

### Event

- [ ] channel-added
- [ ] channel-updated
- [ ] channel-removed
- [ ] guild-emoji-added
- [ ] guild-emoji-updated
- [ ] guild-emoji-deleted
- [ ] friend-request
- [ ] guild-added
- [ ] guild-updated
- [ ] guild-removed
- [ ] guild-request
- [ ] guild-member-added
- [ ] guild-member-updated
- [ ] guild-member-removed
- [ ] guild-member-request
- [ ] guild-role-created
- [ ] guild-role-updated
- [ ] guild-role-deleted
- [x] interaction/button
- [ ] interaction/command
- [x] login-added
- [ ] login-removed
- [ ] login-updated
- [x] message-created
- [ ] message-updated
- [ ] message-deleted
- [ ] reaction-added
- [ ] reaction-removed

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

- [x] button-group
- [x] figure
- [x] image
- [x] location (Receive only)
- [x] pre / code-block
