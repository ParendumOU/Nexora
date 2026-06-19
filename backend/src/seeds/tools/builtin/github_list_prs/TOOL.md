# GitHub List Pull Requests

List PRs for GitHub repo.

## Parameters
- `owner` (string, required): repo owner
- `repo` (string, required): repo name
- `state` (string, optional): `open`, `closed`, or `all` (default: `open`)
- `base` (string, optional): filter by base branch
- `per_page` (integer, optional): results per page (default: 30, max: 100)

## Returns
```json
[
  { "number": 12, "title": "feat: ...", "state": "open", "base": "main", "url": "..." }
]
```
