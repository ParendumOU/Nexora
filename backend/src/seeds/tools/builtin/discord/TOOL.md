# Discord Tool

Interact with Discord servers: send messages, read history, create threads, list channels.

## Required setup
Set `DISCORD_BOT_TOKEN` to a Discord Bot Token. Create one at discord.com/developers/applications → Bot → Reset Token.

Required permissions: `Send Messages`, `Read Message History`, `View Channels`, `Create Public Threads`.

## Actions

### send_message
Send a message to a channel.
```json
{"action": "send_message", "channel_id": "123456789", "content": "Hello from Nexora!"}
```

### reply_thread
Send a message inside an existing thread.
```json
{"action": "reply_thread", "thread_id": "123456789", "content": "Reply here"}
```

### create_thread
Create a new thread on a message.
```json
{"action": "create_thread", "channel_id": "123456789", "message_id": "987654321", "name": "Thread name"}
```

### read_messages
Read recent messages from a channel.
```json
{"action": "read_messages", "channel_id": "123456789", "limit": 20}
```
Optional: `before` (message ID) to fetch messages before a specific message.

### list_channels
List channels in a guild (server).
```json
{"action": "list_channels", "guild_id": "123456789"}
```

### channel_info
Get info about a channel.
```json
{"action": "channel_info", "channel_id": "123456789"}
```

## Notes
- All IDs are Discord snowflake IDs (numeric strings).
- Enable Developer Mode in Discord settings to copy IDs.
