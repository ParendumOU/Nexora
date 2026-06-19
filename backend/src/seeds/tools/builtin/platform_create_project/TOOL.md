# platform_create_project

Create Nexora project. Auto-resolves org from calling agent. Use for bulk-importing repos from GitLab/GitHub as projects.

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `name` | string | yes | Project display name. Must be unique within org. |
| `description` | string | no | Short description. |
| `repo_url` | string | no | Full HTTPS URL (e.g. `https://gitlab.com/group/repo`). |
| `repo_type` | string | no | `gitlab` or `github`. Inferred from `repo_url` if omitted. |
| `repo_branch` | string | no | Default branch. Default `main`. |
| `repo_credential_id` | string | no | id of `git_credentials` row. REQUIRED if `repo_url` is private. Use `platform_list_credentials` first. |
| `is_private` | bool | no | Marks repo as private (UI labelling). |
| `pm_agent_id` | string | no | id of agent to manage this project. |
| `provider_chain_id` | string | no | LLM provider chain default for chats in project. |
| `tools` | list | no | Builtin tool keys enabled for project (additive on top of agent tools). |
| `mcps` | list | no | MCP server configs for project. |
| `env_vars` | object | no | Env vars exposed to agents in project. |
| `skip_if_exists` | bool | no | Return existing project on name collision instead of erroring. Default false. |

## Returns

```json
{"data": {"id": "...", "name": "...", "repo_url": "...", "created": true}}
```

`created: false` when `skip_if_exists` matched existing row.

## Idempotency tip

Bulk imports: always pass `skip_if_exists: true` → re-running after partial failure won't error on duplicates.

## Example

```tool_calls
[{"name": "platform_create_project", "args": {
  "name": "nexora",
  "description": "Multi-tenant AI orchestration platform",
  "repo_url": "https://gitlab.com/parendum/nexora/nexora",
  "repo_type": "gitlab",
  "repo_branch": "main",
  "repo_credential_id": "abc-123",
  "is_private": true,
  "skip_if_exists": true
}}]
```
