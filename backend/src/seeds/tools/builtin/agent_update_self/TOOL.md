# agent_update_self

Modify own agent config at runtime. All changes audit-logged.

Requires: `agent_update_self` in tools list.

## Parameters (all optional)

| Field | Type | Description |
|---|---|---|
| `system_prompt_append` | string | Append to current prompt |
| `system_prompt_replace` | string | Full prompt replacement (destructive) |
| `soul` | object | Merge into soul config; unmentioned keys preserved |
| `description` | string | Update agent description |
| `temperature` | float | LLM temp 0.0–1.0 |
| `max_tokens` | int | Max tokens/res |
| `model_pref` | string | Preferred model ID |
| `skills_add` | string[] | Skill keys to add |
| `skills_remove` | string[] | Skill keys to remove |
| `tools_add` | string[] | Tool keys to add. Security gate: only `always_allowed` tools. Restricted → ask orchestrator. |
| `tools_remove` | string[] | Tool keys to remove |

## Returns

```json
{
  "updated": true,
  "agent_id": "...",
  "changes": {"system_prompt_append": "142 chars", "skills": ["gitlab_read"]},
  "warning": "..." // only if tool_add partially denied
}
```

## Example

```tool_calls
[{"name": "agent_update_self", "args": {
  "system_prompt_append": "## Learned Rule\n\nAlways check for existing issues before creating new ones."
}}]
```

## Notes
- Changes take effect next turn — not mid-task.
- Prefer `system_prompt_append` over `system_prompt_replace`.
- To spawn peers: use `platform_create_agent` (no `agent_update_self` needed).
