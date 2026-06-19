# File Read

Read file from filesystem.

## Parameters
- `path` (string, required): Absolute or relative path to file
- `encoding` (string, optional): File encoding (default: `utf-8`)
- `offset` (integer, optional): Line to start reading from — 1-indexed
- `limit` (integer, optional): Max lines to read

## Returns
```json
{
  "path": "/app/src/main.py",
  "content": "file contents here...",
  "lines": 42
}
```
