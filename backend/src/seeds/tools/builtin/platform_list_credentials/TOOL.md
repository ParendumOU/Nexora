# platform_list_credentials

List git credentials registered for current org. Metadata only — raw token values never exposed.

Use when bulk-importing repos → pick correct `repo_credential_id` for each `platform_create_project` call.

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `provider` | string | no | `gitlab` / `github` filter. Omit for all. |

## Returns

```json
{"data": {"credentials": [
  {"id": "abc-123", "provider": "gitlab", "label": "GitLab — connorlilhomer",
   "base_url": "https://gitlab.com", "created_at": "..."}
], "count": 1}}
```

## Example

```tool_calls
[{"name": "platform_list_credentials", "args": {"provider": "gitlab"}}]
```
