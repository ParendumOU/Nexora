# note_replace

Overwrite entire shared notes scratchpad for current chat tree. Destructive — use only when intentionally discarding previous notes (e.g. consolidating into clean final report). Prefer `note_append` for incremental additions.

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `content` | string | yes | New full markdown body for notes. |

## Returns

```json
{"data": {"length": 1234, "chat_id": "<root>"}}
```

## Example

```tool_calls
[{"name": "note_replace", "args": {"content": "# Consolidated inventory\n\n..."}}]
```
