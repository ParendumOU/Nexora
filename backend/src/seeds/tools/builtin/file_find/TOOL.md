# File Find

Search files by pattern or content.

## Parameters
- `path` (string, required): Root dir to search
- `pattern` (string, optional): Glob pattern (e.g. `*.ts`, `**/*.json`)
- `contains` (string, optional): Text file content must contain
- `max_results` (integer, optional): Max results (default: 50)

## Returns
```json
{
  "matches": [
    { "path": "/app/src/main.py", "line": 42, "snippet": "matching line..." }
  ]
}
```
