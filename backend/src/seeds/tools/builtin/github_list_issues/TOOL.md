# GitHub List Issues

List issues for GitHub repo.

## Parameters
- `owner` (string, required): repo owner
- `repo` (string, required): repo name
- `state` (string, optional): `open`, `closed`, or `all` (default: `open`)
- `labels` (array, optional): filter by label names
- `per_page` (integer, optional): results per page (default: 30, max: 100)

## Returns
```json
[
  { "number": 42, "title": "Bug: ...", "state": "open", "labels": ["bug"], "url": "..." }
]
```

## Empty results

`[]` = valid response. No issues match `state` in external GitHub repo. NOT error.

**Got empty list but expected open issues** → issues may have been closed on GitHub outside platform. Retry with `state: "all"` or `state: "closed"` before concluding nothing to work on. Never report "no issues found" and stop — check all states first.
