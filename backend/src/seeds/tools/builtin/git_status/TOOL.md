# Git Status

Show working tree status of local Git repo.

## Parameters
- `path` (string, required): Path to git repo

## Returns
```json
{
  "branch": "main",
  "staged": ["src/main.py"],
  "unstaged": ["README.md"],
  "untracked": ["new_file.txt"],
  "clean": false
}
```
