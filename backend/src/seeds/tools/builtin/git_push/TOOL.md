# Git Push

Push commits to remote repo.

## Parameters
- `path` (string, required): Path to git repo
- `remote` (string, optional): Remote name (default: `origin`)
- `branch` (string, optional): Branch to push (default: current branch)
- `force` (boolean, optional): Force push — dangerous (default: false)

## Returns
```json
{ "remote": "origin", "branch": "main", "commits_pushed": 2 }
```
