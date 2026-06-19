# Git Commit

Stage changes → create commit.

## Parameters
- `path` (string, required): Path to git repo
- `message` (string, required): Commit message
- `add_all` (boolean, optional): Stage all changes before commit (default: true)

## Returns
```json
{ "commit": "abc123def456", "message": "feat: add new feature", "files_changed": 3 }
```
