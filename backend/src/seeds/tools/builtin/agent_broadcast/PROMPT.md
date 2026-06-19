### agent_broadcast
Send an async message to all agents in a channel, explicit agent IDs, or all org agents.

```tool_calls
[{"name": "agent_broadcast", "args": {"subject": "Daily standup", "body": "Please share your status.", "channel": "standup"}}]
```

Args: `subject` (required), `body` (required), `channel` (string — sends to agents subscribed to this channel), `agent_ids` (list — explicit targets), `mode` ("async"). Omit channel/agent_ids to broadcast to all org agents.
Returns: `dispatched` count, list of recipients with `task_id`.
