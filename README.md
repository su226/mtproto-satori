# mtproto-satori

A [Satori](https://satori.chat) implementation based on MTProto using [Kurigram](https://github.com/KurimuzonAkuma/kurigram) and [satori-python](https://github.com/RF-Tar-Railt/satori-python).

## Usage

Obtain your `api_id` and `api_hash` at <https://my.telegram.org>.

Create `config.toml`.

```toml
host = "127.0.0.1"
# Optional, defaults to "127.0.0.1"

port = 5140
# Optional, defaults to 5140

path = "/satori"
# Optional, defaults to ""

token = "0123456789abcdef"
# Optional, defaults to ""

api_id = 12345
# Required, example value here won't work

api_hash = "0123456789abcdef0123456789abcdef"
# Required, example value here won't work

phone = ""
# Either phone or bot_token is required

password = ""
# Required if your account has 2FA

bot_token = ""
# Either phone or bot_token is required

ignore_automatic_forward_interval = 10
# Optional, defaults to 10(s)
# If bot is in both a channel and its linked group, channel messages will be received twice.
# Once in the channel, and once again in the group.
# Enable this option to ignore channel message in the group, or set to 0 to disable.
# Not works when bot is only in one side.

[proxy]
# Optional

scheme = "socks5"
# Required, "http", "socks4" or "socks5"

hostname = "127.0.0.1"
# Required

port = 1234
# Required

username = "username"
# Optional

password = "password"
# Optional

[merge_media_groups]
# Optional
# Whethre to merge media group when...

receive = 0.1
# Optional, defaults to 0.1(s).
# When receive messages, wait for a period to fully receive media groups.
# Higher value means higher latency when receiving media groups.
# If media groups are incomplete, try increase it.
# Set to 0 to disable.
```

Install dependencies with `uv sync`.

Start with `uv run mtproto-satori`.

## Features

### API

Methods not usable by bots are **UNTESTED**, since I only use this on bots, use at your own risk.

- [x] channel.get
- [ ] channel.list ([Not usable by bots](https://docs.kurigram.icu/api/methods/get_forum_topics/#pyrogram.Client.get_forum_topics))
- [x] channel.create
- [x] channel.update
- [x] channel.delete
- [x] channel.mute
- [ ] friend.list ([Not usable by bots](https://docs.kurigram.icu/api/methods/get_contacts/#pyrogram.Client.get_contacts))
- [ ] friend.delete ([Not usable by bots](https://docs.kurigram.icu/api/methods/delete_contacts/#pyrogram.Client.delete_contacts))
- [ ] friend.approve ([Not usable by bots](https://docs.kurigram.icu/api/methods/add_contact/#pyrogram.Client.add_contact))
- [x] guild.get
- [ ] guild.list ([Not usable by bots](https://docs.kurigram.icu/api/methods/get_dialogs/#pyrogram.Client.get_dialogs))
- [ ] guild.approve ([Not usable by bots](https://docs.kurigram.icu/api/methods/join_chat/#pyrogram.Client.join_chat))
- [x] guild.member.get
- [x] guild.member.list
- [x] guild.member.kick
- [x] guild.member.mute
- [x] guild.member.approve
- [x] guild.member.role.set
- [x] guild.member.role.unset
- [x] guild.role.list
- [ ] guild.role.create (Not supported in Telegram)
- [ ] guild.role.update (Not supported in Telegram)
- [ ] guild.role.delete (Not supported in Telegram)
- [x] login.get
- [x] message.create
- [x] message.get
- [x] message.delete
- [x] message.update
- [ ] message.list ([Not usable by bots](https://docs.kurigram.icu/api/methods/search_messages/#pyrogram.Client.search_messages))
- [x] reaction.create
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
- [x] guild-member-added ([Not usable by users](https://docs.kurigram.icu/api/decorators/#pyrogram.Client.on_chat_member_updated))
- [x] guild-member-updated ([Not usable by users](https://docs.kurigram.icu/api/decorators/#pyrogram.Client.on_chat_member_updated))
- [x] guild-member-removed ([Not usable by users](https://docs.kurigram.icu/api/decorators/#pyrogram.Client.on_chat_member_updated))
- [x] guild-member-request ([Not usable by users](https://docs.kurigram.icu/api/decorators/#pyrogram.Client.on_chat_join_request))
- [ ] guild-role-created (Not supported in Telegram)
- [ ] guild-role-updated (Not supported in Telegram)
- [ ] guild-role-deleted (Not supported in Telegram)
- [x] interaction/button
- [x] interaction/command
- [x] login-added
- [x] login-removed
- [x] login-updated
- [x] message-created
- [x] message-updated
- [x] message-deleted (Limited on bots)[^1]
- [x] reaction-added ([Not usable by users](https://docs.kurigram.icu/api/decorators/#pyrogram.Client.on_message_reaction_count))
- [x] reaction-removed ([Not usable by users](https://docs.kurigram.icu/api/decorators/#pyrogram.Client.on_message_reaction_count))

[^1]: Bots can only receive all message-deleted events in direct messages and (basic) groups. In supergroups, only message-deleted events related to the bot are received. (Like a "enforced" privacy mode) In channels, no message-deleted events can be received.

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

Roles:

| Role            | Set behavior        | Unset behavior |
| --------------- | ------------------- | -------------- |
| `owner`         | Error               | Error          |
| `administrator` | Promote             | Demote         |
| `member`        | Demote / Unrestrict | Kick           |
| `restricted`    | Restrict            | Unrestrict     |
| `left`          | Kick                | Error          |
| `banned`        | Ban                 | Unban          |
