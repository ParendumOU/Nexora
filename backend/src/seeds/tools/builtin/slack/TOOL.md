# Slack Tool

Interact with Slack workspaces: send messages, read history, manage threads, list channels, look up users.

## Required setup
Set `SLACK_BOT_TOKEN` to a Slack Bot User OAuth Token (`xoxb-...`). Create one at api.slack.com/apps → OAuth & Permissions.

Required scopes: `chat:write`, `channels:history`, `channels:read`, `groups:history`, `groups:read`, `im:history`, `im:read`, `users:read`.

## Actions

### send_message
Send a message to a channel or DM.
```json
{"action": "send_message", "channel": "#general", "text": "Hello from Nexora!"}
```

### reply_thread
Reply in a thread.
```json
{"action": "reply_thread", "channel": "#general", "thread_ts": "1234567890.123456", "text": "Reply here"}
```

### read_messages
Read recent messages from a channel.
```json
{"action": "read_messages", "channel": "#general", "limit": 10}
```
Optional: `oldest` (Unix timestamp string) to fetch messages after a specific time.

### list_channels
List public channels in the workspace.
```json
{"action": "list_channels", "limit": 50}
```
Optional: `types` (default `"public_channel"`) — comma-separated: `public_channel,private_channel,im,mpim`.

### channel_info
Get info about a specific channel.
```json
{"action": "channel_info", "channel": "#general"}
```

### user_info
Look up a Slack user by ID or email.
```json
{"action": "user_info", "user": "U012AB3CD"}
```
Or by email:
```json
{"action": "user_info", "email": "alice@example.com"}
```

## Channel formats
Channels can be specified as `#name`, `name`, or the channel ID (`C012AB3CD`).
