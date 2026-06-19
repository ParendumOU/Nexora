# note_append

Append markdown section to shared notes for current chat tree. Platform auto-prefixes heading with agent name + timestamp — attribution automatic. Sub-agent writes propagate to root chat instantly — orchestrator and user see them live.

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `content` | string | yes | Markdown body to append. |
| `heading` | string | no | Short section title. Default: agent name. |

## Returns

```json
{"data": {"length": 4321, "chat_id": "<root>"}}
```

## Example — sub-agent posting findings

```tool_calls
[{"name": "note_append", "args": {
  "heading": "GitLab inventory (218 repos)",
  "content": "Listado completo por namespace:\n\n- parendum/nexora/nexora — https://gitlab.com/...\n- parendum/nexora/... \n..."
}}]
```
