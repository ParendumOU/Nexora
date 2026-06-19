# platform_import_repos

Bulk-import GitHub/GitLab repos as Nexora projects. Fetches live repo list from credential, matches requested repos, creates projects with PM agents. Skips duplicates by default.

## Typical flow

```
1. platform_list_credentials    → pick credential_id
2. platform_list_repos          → inspect available repos (optional but recommended)
3. platform_import_repos        → import selected repos as projects
```

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `credential_id` | string | yes | id from `platform_list_credentials` |
| `repos` | list | one of these three | Explicit list — each item: `{full_name?, name?, description?, default_branch?}`. Matched against live repo list by `full_name` first, then `name`. |
| `groups` | list | one of these three | Group/org display names (case-insensitive). Imports all repos from matching groups. |
| `import_all` | bool | one of these three | `true` — import every accessible repo from credential. |
| `skip_if_exists` | bool | no | Skip existing project names instead of erroring. Default `true`. |

## Returns

```json
{
  "data": {
    "created": [{"id": "...", "name": "My Service", "repo_url": "...", "full_name": "org/my-service"}],
    "skipped": [{"name": "Already Exists", "reason": "name_exists"}],
    "errors": [],
    "summary": {"created_count": 5, "skipped_count": 1, "error_count": 0, "total_considered": 6}
  }
}
```

## Examples

**Import specific repos by full_name:**
```tool_calls
[{"name": "platform_import_repos", "args": {
  "credential_id": "abc-123",
  "repos": [
    {"full_name": "my-org/backend-service"},
    {"full_name": "my-org/frontend-app", "default_branch": "develop"}
  ]
}}]
```

**Import all repos from group:**
```tool_calls
[{"name": "platform_import_repos", "args": {
  "credential_id": "abc-123",
  "groups": ["My Backend Team", "Infrastructure"]
}}]
```

**Import everything:**
```tool_calls
[{"name": "platform_import_repos", "args": {
  "credential_id": "abc-123",
  "import_all": true
}}]
```

## Notes

- Project names use repo display name (`name` field, e.g. `"My Backend Service"`), not slug.
- Each project gets auto-created PM agent.
- `repo_credential_id` and `default_branch` stored in project meta for git tool access.
- Broadcasts `projects_imported` event → UI updates in real-time.
