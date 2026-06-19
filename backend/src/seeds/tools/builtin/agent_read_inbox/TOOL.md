# agent_read_inbox

Read msgs sent to you by other agents. Part of AgentBus messaging system.

## Parameters

| Field | Type | Default | Description |
|---|---|---|---|
| `unread_only` | bool | false | Return only undelivered/unread msgs (status=`delivered`) |
| `status` | string | `all` | Filter: `delivered`, `replied`, `timeout`, `all` |
| `limit` | int | 20 | Max msgs to return (max 100) |
| `offset` | int | 0 | Pagination offset |

## Returns

```json
{
  "messages": [
    {
      "id": "...",
      "from_agent_id": "...",
      "from_agent_name": "Security Analyst",
      "subject": "Review needed",
      "body": "...",
      "reply_to_id": null,
      "reply_body": null,
      "status": "delivered",
      "created_at": "2026-05-24T08:00:00Z"
    }
  ],
  "count": 5
}
```

## Usage

```tool_calls
[{"name": "agent_read_inbox", "args": {"unread_only": true, "limit": 10}}]
```

## Notes
- Reply via `send_message_to_agent` with `reply_to_id` set to msg `id`.
- Msgs arrive as Tasks too — may already be in task queue.
- Use `unread_only: true` in standup/sync routines.

## AgentBus tools
- `send_message_to_agent` — direct 1:1 msg (sync or async)
- `agent_read_inbox` — read inbox (this tool)
- `agent_broadcast` — send to channel or all agents
- `list_available_agents` — discover peers by name/type
