# Read File

Read contents of any accessible file on filesystem.

## Usage
- Use `offset` + `limit` for large files → avoid reading too much at once
- Use `file_find` to locate files when path uncertain
- Binary files: read metadata only — no display of binary content

## Example
```tool_calls
[{"name": "read_file", "args": {"path": "/app/src/main.py", "offset": 1, "limit": 50}}]
```
