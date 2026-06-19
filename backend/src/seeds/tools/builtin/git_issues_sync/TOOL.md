# Sync Git Issues

Import open issues from GitHub/GitLab repo → platform issue tracker.

## Parameters
- `repo_url` (string, optional): Repo URL to sync from. Defaults to project's linked repo.
- `labels` (array, optional): Filter by label strings — import issues matching at least one label.
- `limit` (integer, optional): Max issues to import. Default: 50.

## Returns
```json
{
  "imported": 12,
  "skipped": 3,
  "issues": [{ "id": "...", "title": "...", "source": "github" }]
}
```

## Notes
- Skips issues already in tracker — matched by source URL.
- Requires GitHub or GitLab integration configured on org.
