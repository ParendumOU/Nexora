# Shell Run

Execute shell command in agent's container env.

## Parameters
- `command` (string, required): shell command to execute
- `cwd` (string, optional): working directory (default: `/app`)
- `timeout` (integer, optional): timeout in seconds (default: 60)
- `env` (object, optional): additional env vars

## Returns
```json
{
  "stdout": "output here...",
  "stderr": "",
  "exit_code": 0
}
```

## Notes
- Commands run inside backend Docker container
- Use `docker` commands for cross-container ops
- Destructive commands (`rm -rf`, etc.) unrestricted — use with care
