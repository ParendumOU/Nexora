# GitLab List Merge Requests

List MRs for GitLab project.

## Parameters
- `project_id` (string, required): project ID or path
- `state` (string, optional): `opened`, `closed`, `merged`, or `all` (default: `opened`)
- `target_branch` (string, optional): filter by target branch
- `per_page` (integer, optional): results per page (default: 20, max: 100)

## Returns
```json
[
  { "iid": 3, "title": "feat: ...", "state": "opened", "target_branch": "main" }
]
```
