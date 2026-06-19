### send_message_to_agent
Send a direct 1:1 message to another agent and optionally wait for a reply.

```tool_calls
[{"name": "send_message_to_agent", "args": {"to_agent_id": "<id>", "subject": "Need help with X", "body": "Can you review this?", "mode": "async"}}]
```

Args: `to_agent_id` (required), `subject` (required), `body` (required), `mode` ("async" or "sync"). Use `list_available_agents` first to find the target agent's ID.
