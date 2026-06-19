# Write File

Create or overwrite files on filesystem.

## Usage
- Read existing file first before overwriting (use `read_file`)
- Targeted edits over full rewrites when few lines change
- Create parent dirs if missing
- UTF-8 encoding default

## Example
```tool_calls
[{"name": "write_file", "args": {"path": "/app/src/config.py", "content": "DEBUG = True\n"}}]
```
