# platform_list_repos

List all repos accessible with stored git credential. Flat list with group context — discover repos before importing as projects.

## Typical flow

```
1. platform_list_credentials        → pick credential_id
2. platform_list_repos              → see available repos, note full_name / web_url
3. platform_import_repos            → bulk-import selected repos as projects
```

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `credential_id` | string | yes | id from `platform_list_credentials` |
| `group` | string | no | Filter by group/org name (case-insensitive substring match) |
| `visibility` | string | no | `"public"` or `"private"` — filter by repo visibility |

## Returns

```json
{
  "data": {
    "credential_id": "...",
    "provider": "gitlab",
    "repos": [
      {
        "id": "123",
        "name": "My Backend Service",
        "full_name": "my-org/backend-service",
        "web_url": "https://gitlab.com/my-org/backend-service",
        "description": "...",
        "is_private": true,
        "default_branch": "main",
        "group": "My Org",
        "group_type": "group"
      }
    ],
    "count": 42
  }
}
```

## Notes

- `name` = display name (e.g. `"My Backend Service"`), not slug.
- `full_name` = namespace path (e.g. `"my-org/backend-service"`).
- `group` = display name of owning group/org/user namespace.
- Large accounts: call may take seconds — fetches all groups/subgroups concurrently.

## Example

```tool_calls
[{"name": "platform_list_repos", "args": {
  "credential_id": "abc-123",
  "group": "backend-team",
  "visibility": "private"
}}]
```
