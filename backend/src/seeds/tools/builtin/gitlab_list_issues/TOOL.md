# GitLab List Issues

List issues for GitLab project.

## Parameters
- `project_id` (string, required): project ID or path
- `state` (string, optional): `opened`, `closed`, or `all` (default: `opened`)
- `labels` (array, optional): filter by label names
- `per_page` (integer, optional): results per page (default: 20, max: 100)

## Returns
```json
[
  { "iid": 5, "title": "Bug: ...", "state": "opened", "labels": ["bug"] }
]
```

## Empty results

`[]` = valid response. No issues match `state` in external GitLab project. NOT error.

**Got empty list but expected open issues** → issues may have been closed on GitLab outside platform. Retry with `state: "all"` or `state: "closed"` before concluding nothing to work on. Never report "no issues found" and stop — check all states first.
