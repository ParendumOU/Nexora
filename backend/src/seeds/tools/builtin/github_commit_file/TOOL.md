# GitHub Commit File

Create or update file in GitHub repo.

## Parameters
- `owner` (string, required): repo owner
- `repo` (string, required): repo name
- `path` (string, required): file path within repo
- `content` (string, required): new file content (will be base64-encoded)
- `message` (string, required): commit message
- `branch` (string, optional): target branch (default: default branch)
- `sha` (string, optional): existing file SHA — required when updating existing file

## Returns
```json
{ "commit": "abc123", "path": "src/config.py" }
```
