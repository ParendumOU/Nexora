# File Write

Write or overwrite file on filesystem.

## Parameters
- `path` (string, required): Absolute or relative path to write
- `content` (string, required): File content
- `encoding` (string, optional): File encoding (default: `utf-8`)
- `create_dirs` (boolean, optional): Create parent dirs if missing (default: true)

## Returns
```json
{ "path": "/app/src/config.py", "bytes_written": 512 }
```
