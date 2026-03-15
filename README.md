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

Methods not usable by bots are **UNTESTED**, since I only use this on bots, use at your own risk.

- [x] channel.get
- [ ] channel.list (Not usable by bots)
- [ ] channel.create
- [ ] channel.update
- [ ] channel.delete
- [ ] channel.mute (Not supported in Telegram)
- [ ] friend.list (Not usable by bots)
- [ ] friend.delete (Not usable by bots)
- [ ] friend.approve (Not usable by bots)
- [x] guild.get
- [ ] guild.list (Not usable by bots)
- [ ] guild.approve (Not usable by bots)
- [x] guild.member.get
- [x] guild.member.list
- [ ] guild.member.kick
- [ ] guild.member.mute
- [ ] guild.member.approve
- [ ] guild.member.role.set
- [ ] guild.member.role.unset
- [ ] guild.role.list
- [ ] guild.role.create (Not supported in Telegram)
- [ ] guild.role.update (Not supported in Telegram)
- [ ] guild.role.delete (Not supported in Telegram)
- [x] login.get
- [x] message.create
- [x] message.get
- [x] message.delete
- [x] message.update
- [ ] message.list (Not usable by bots)
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
- [ ] guild-role-created (Not supported in Telegram)
- [ ] guild-role-updated (Not supported in Telegram)
- [ ] guild-role-deleted (Not supported in Telegram)
- [x] interaction/button
- [ ] interaction/command
- [x] login-added
- [ ] login-removed
- [ ] login-updated
- [x] message-created
- [x] message-updated
- [x] message-deleted (Limited on bots)[^1]
- [ ] reaction-added
- [ ] reaction-removed

[^1]: Bots can only receive message-deleted in direct messages and (regular) groups, not supergroups or channels.

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

## Implementation details

Input user ID: A username or [bot API dialog ID](https://core.telegram.org/api/bots/ids). You can get "user" info from supergroups/channels since supergroups/channels can act like anonymous users.

Output user ID: A [bot API dialog ID](https://core.telegram.org/api/bots/ids). Usernames will be resolved.

Input channel ID: "xxxxxx" for users/groups/supergroups without threads/channels, "xxxxxx:yyy" for supergroups with threads, where "xxxxxx" is a username or [bot API dialog ID](https://core.telegram.org/api/bots/ids), and "yyy" is a [message (thread) ID](https://core.telegram.org/api/threads).

Output channel ID: "xxxxxx" for users/groups/supergroups without threads/channels, "xxxxxx:yyy" for supergroups with threads, where "xxxxxx" is a [bot API dialog ID](https://core.telegram.org/api/bots/ids) (usernames will be resolved), and "yyy" is a [message (thread) ID](https://core.telegram.org/api/threads).

Input guild ID: A username or [bot API dialog ID](https://core.telegram.org/api/bots/ids), excpet users have no guild.

Output guild ID: A [bot API dialog ID](https://core.telegram.org/api/bots/ids), usernames will be resolved, excpet users have no guild.

Message ID: "yyy" for messages quoted from same chat, "xxxxxx:yyy" for messages quoted from different chat. `message.get` will automatically use chat id in message id if exists.
