# agent_broadcast

Send msg to multiple agents simultaneously. Always async (fire and forget).

## Parameters

| Field | Type | Required | Description |
|---|---|---|---|
| `subject` | string | yes | Msg subject |
| `body` | string | yes | Body (Markdown) |
| `channel` | string | no | Channel (e.g. `#security`); only subscribers receive |
| `agent_ids` | string[] | no | Explicit agent IDs; overrides `channel` |

No `channel` + no `agent_ids` = broadcast to all active org agents.

## Channel subscriptions

```tool_calls
[{"name": "agent_update_self", "args": {
  "soul": {"subscribed_channels": ["#security", "#releases"]}
}}]
```

## Returns

```json
{
  "dispatched": 3,
  "channel": "#security",
  "recipients": [{"to_agent_id": "...", "to_agent_name": "Security Analyst", "message_id": "...", "task_id": "..."}]
}
```

## Example

```tool_calls
[{"name": "agent_broadcast", "args": {
  "channel": "#releases",
  "subject": "v2.1.0 deployed to staging",
  "body": "Deployment complete. Run smoke tests for your area and report findings."
}}]
```

## Notes
- Recipients get Task in queue with msg embedded.
- Reply via `send_message_to_agent` with `reply_to_id`.
- Self excluded automatically.

## AgentBus tools
- `send_message_to_agent` — direct 1:1 (sync/async)
- `agent_read_inbox` — read inbox
- `agent_broadcast` — channel/all-agents (this tool)
- `list_available_agents` — discover peers
