# Git Clone

Clone Git repo to local dir.

## Parameters
- `url` (string, required): Repo URL — HTTPS or SSH
- `destination` (string, optional): Local path to clone into
- `branch` (string, optional): Branch to checkout after clone
- `depth` (integer, optional): Shallow clone depth

## Returns
```json
{ "path": "/workspace/my-repo", "branch": "main", "commit": "abc123" }
```
