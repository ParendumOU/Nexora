### list_available_agents
Discover active agents in the org — use this before sending messages to find agent IDs.

```tool_calls
[{"name": "list_available_agents", "args": {"agent_type": "coordinator"}}]
```

Args: `agent_type` (string filter, optional), `name` (string search, optional). Returns list of `{id, name, agent_type, description}`.
