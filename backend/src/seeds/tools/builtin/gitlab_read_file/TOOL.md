# GitLab Read File

Read file from GitLab repo.

## Parameters
- `project_id` (string, required): project ID or path
- `file_path` (string, required): file path within repo
- `ref` (string, optional): branch, tag, or commit SHA (default: default branch)

## Returns
```json
{ "file_path": "src/main.py", "content": "...", "size": 1024 }
```
