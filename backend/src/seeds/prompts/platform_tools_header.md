## Platform Tools — `tool_calls` fence is ONLY action mechanism

Prose without fence = nothing happens. Only fenced JSON arrays execute.

**Fence format — EXACT syntax required:**
```tool_calls
[{"name":"task_create","args":{"title":"..."}},{"name":"log_entry","args":{"message":"...","level":"info"}}]
```
Language tag (`tool_calls`) MUST be on the same line as the opening backticks. Never put it on the next line. Single JSON array, no trailing commas, no nested fences.

### Available tools
