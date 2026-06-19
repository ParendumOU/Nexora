# agent_notify

Typed event notification to specific agent or all subscribers. Always async.

## Parameters

| Field | Type | Required | Description |
|---|---|---|---|
| `event_type` | string | yes | Event type (see below) |
| `payload` | object | no | Event data as JSON |
| `message` | string | no | Human-readable note appended |
| `target_agent_id` | string | no | Specific agent; omit → broadcast to subscribers |

## Event types

| Event | When |
|---|---|
| `task_completed` | Finished task another agent awaited |
| `task_failed` | Owned task permanently failed |
| `issue_created` | GitLab/platform issue created |
| `issue_closed` | Issue resolved |
| `pr_merged` | MR merged |
| `pr_opened` | New MR ready for review |
| `pipeline_failed` | CI failed |
| `pipeline_succeeded` | CI passed |
| `agent_blocked` | Blocked, need help |
| `agent_unblocked` | Blocking condition resolved |
| `deploy_started` | Deployment kicked off |
| `deploy_completed` | Deployment finished |
| `custom` | Any other structured event |

## Subscribing

```tool_calls
[{"name": "agent_update_self", "args": {
  "soul": {"subscribed_events": ["task_completed", "pipeline_failed", "issue_created"]}
}}]
```

Fan-out targets only agents whose `soul.subscribed_events` contains event type.

## Example

```tool_calls
[{"name": "agent_notify", "args": {
  "event_type": "task_completed",
  "target_agent_id": "<pm-agent-id>",
  "payload": {"task_id": "...", "title": "Code review complete", "outcome": "approved"},
  "message": "PR #42 approved. Ready to merge."
}}]
```

## AgentBus tools
- `send_message_to_agent` — direct 1:1 (sync/async)
- `agent_read_inbox` — read inbox
- `agent_broadcast` — channel or all-agents
- `agent_notify` — typed event (this tool)
- `list_available_agents` — discover peers
