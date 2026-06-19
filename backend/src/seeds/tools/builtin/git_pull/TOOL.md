# Git Pull

Pull latest changes from remote repo.

## Parameters
- `path` (string, required): Path to git repo
- `remote` (string, optional): Remote name (default: `origin`)
- `branch` (string, optional): Branch to pull (default: current branch)
- `rebase` (boolean, optional): Rebase instead of merge (default: false)

## Returns
```json
{ "commits_pulled": 5, "files_changed": 12 }
```
