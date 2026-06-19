# Create Tool

Create new tool definition in platform for current org.

## Parameters
- `key` (string, required): Unique tool identifier (snake_case).
- `name` (string, required): Human-readable tool name.
- `description` (string, optional): What tool does and when to use it.
- `category` (string, optional): Grouping category (e.g. `platform`, `git`, `web`).
- `tool_md` (string, optional): TOOL.md content — usage docs injected into agent context when tool enabled.
- `executor` (string, optional): Python executor code (placed in `executor.py`).
- `env_vars` (array, optional): Required env var names.
- `always_allowed` (boolean, optional): Skip approval gate. Default: false.

## Returns
```json
{ "tool_id": "...", "key": "...", "name": "..." }
```

## Notes
- Always allowed; no approval gate.
- Custom tools stored under `seeds/tools/custom/` — override builtin tools of same key.
- Requires corresponding executor impl to function at runtime.
