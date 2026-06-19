# platform_update_project

Patch existing project. Only passed fields updated.

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `project_id` | string | yes | id of project to update. |
| `name` | string | no | Rename. |
| `description` | string | no | |
| `repo_url` | string | no | |
| `repo_type` | string | no | gitlab/github |
| `repo_branch` | string | no | |
| `repo_credential_id` | string | no | |
| `is_private` | bool | no | |
| `pm_agent_id` | string | no | |
| `provider_chain_id` | string | no | |
| `tools` | list | no | Full replacement of tool keys. |
| `mcps` | list | no | Full replacement of MCP configs. |
| `env_vars` | object | no | Full replacement of env vars. |
| `status` | string | no | `active` / `archived`. |

## Returns

```json
{"data": {"id": "...", "name": "...", "updated_fields": [...]}}
```

## Example — set PM agent + tools after creation

```tool_calls
[{"name": "platform_update_project", "args": {
  "project_id": "abc-123",
  "pm_agent_id": "xyz-789",
  "tools": ["gitlab_api", "shell_run"]
}}]
```
