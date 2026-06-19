# Docker Run

Run command in Docker container.

## Parameters
- `container` (string, required): container name or ID to exec into (use `image` for new container)
- `command` (string, required): command to execute
- `image` (string, optional): Docker image to run if starting new container
- `env` (object, optional): env vars

## Returns
```json
{ "stdout": "...", "stderr": "", "exit_code": 0 }
```
