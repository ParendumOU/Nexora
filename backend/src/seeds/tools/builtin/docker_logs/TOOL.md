# Docker Logs

Fetch logs from Docker container.

## Parameters
- `container` (string, required): container name or ID
- `tail` (integer, optional): lines from end (default: 100)
- `since` (string, optional): logs since timestamp or duration (e.g. `10m`, `2024-01-01T00:00:00`)
- `timestamps` (boolean, optional): include timestamps (default: false)

## Returns
```json
{ "container": "backend", "logs": "log line 1\nlog line 2\n..." }
```
