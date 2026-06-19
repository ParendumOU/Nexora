# GitHub Read File

Read file from GitHub repo.

## Parameters
- `owner` (string, required): repo owner
- `repo` (string, required): repo name
- `path` (string, required): file path within repo
- `ref` (string, optional): branch, tag, or commit SHA (default: default branch)

## Returns
```json
{ "path": "src/main.py", "content": "file content...", "sha": "abc123" }
```
