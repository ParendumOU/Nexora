# list_available_agents

Returns all active agents in org. Use before `send_message_to_agent` — find right agent ID, understand capabilities.

## Example

```tool_calls
[{"name": "list_available_agents", "args": {}}]
```

## Response

```json
{
  "agents": [
    {
      "id": "abc-123",
      "name": "Backend Engineer",
      "description": "Specialises in Python, FastAPI, and PostgreSQL.",
      "agent_type": "custom",
      "skills": ["git_read", "shell_run"]
    }
  ],
  "total": 1
}
```

Pick agent whose description/skills best match req → use `id` in `send_message_to_agent`.
