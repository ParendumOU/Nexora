# platform_list_projects

List projects in current org. Filter by name fragment or `repo_url` substring.

## Arguments

| arg | type | required | notes |
|-----|------|----------|-------|
| `search` | string | no | Case-insensitive substring match on name OR `repo_url`. |
| `status` | string | no | `active` (default) / `archived` / `all`. |

## Returns

```json
{"data": {"projects": [{"id": "...", "name": "...", "repo_url": "...", "status": "active"}], "count": 3}}
```

## Example — check existence before bulk import

```tool_calls
[{"name": "platform_list_projects", "args": {}}]
```
