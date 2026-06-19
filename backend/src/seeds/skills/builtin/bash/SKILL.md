# Bash Shell

Run shell cmds in sandboxed container.

## Available commands
Standard Unix/Linux: `ls`, `cat`, `grep`, `find`, `curl`, `python3`, `node`, `git`, `docker`, etc.

## Usage
- Inspect cwd with `ls` before writing files
- Use `which <cmd>` → verify tool available before relying on it
- Pipe to `head` or `tail` for large output
- Use `set -e` in multi-step scripts → exit on first error

## Example
```tool_calls
[{"name": "shell_run", "args": {"command": "find /app/src -name '*.py' | head -20"}}]
```
