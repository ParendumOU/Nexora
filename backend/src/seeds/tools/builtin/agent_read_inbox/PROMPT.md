### agent_read_inbox
Read async messages sent to you by other agents via the AgentBus.

```tool_calls
[{"name": "agent_read_inbox", "args": {"unread_only": true, "limit": 20}}]
```

Args: `unread_only` (bool, default true), `status` (string filter), `limit` (int, max 50), `offset` (int).
Returns: list of messages with `from_agent_name`, `subject`, `body`, `status`, `delivered_at`.
