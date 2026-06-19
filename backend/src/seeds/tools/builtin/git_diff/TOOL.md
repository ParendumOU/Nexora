# Git Diff

Show file diffs in git repo.

## Parameters
- `path` (string, required): Path to git repo
- `staged` (boolean, optional): Staged changes only (default: false)
- `from_ref` (string, optional): Base commit/branch for comparison
- `to_ref` (string, optional): Target commit/branch for comparison
- `file` (string, optional): Limit diff to specific file

## Returns
```json
{ "diff": "--- a/file.py\n+++ b/file.py\n@@ ... @@\n..." }
```
