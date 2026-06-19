# File List

List files + dirs at path.

## Parameters
- `path` (string, required): Dir path to list
- `recursive` (boolean, optional): List recursively (default: false)
- `pattern` (string, optional): Glob filter (e.g. `*.py`)

## Returns
```json
{
  "path": "/app/src",
  "entries": [
    { "name": "main.py", "type": "file", "size": 2048 },
    { "name": "api", "type": "directory" }
  ]
}
```
