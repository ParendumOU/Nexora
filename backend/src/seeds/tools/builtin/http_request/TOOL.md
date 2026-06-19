# HTTP Request

Make HTTP requests to external APIs and web services.

## Parameters
- `method` (string, required): HTTP method — GET, POST, PUT, PATCH, DELETE
- `url` (string, required): Absolute URL (http:// or https://)
- `headers` (object, optional): Key-value request headers
- `body` (any, optional): Request body — JSON object or string
- `timeout` (integer, optional): Seconds before timeout (default: 30)
- `auth` (object, optional): Authentication — `{"type": "bearer", "token": "..."}` or `{"type": "basic", "username": "...", "password": "..."}`

## Returns
```json
{
  "status": 200,
  "content_type": "application/json",
  "body": "..."
}
```

## Security
Set `HTTP_TOOL_ALLOWED_ORIGINS` (comma-separated base URLs) to restrict which hosts agents can reach. If unset, all external URLs are permitted (development only).

```
HTTP_TOOL_ALLOWED_ORIGINS=https://api.example.com,https://hooks.slack.com
```

## Examples

### GET with Bearer auth
```json
{
  "method": "GET",
  "url": "https://api.example.com/users",
  "auth": {"type": "bearer", "token": "my-token"}
}
```

### POST JSON
```json
{
  "method": "POST",
  "url": "https://api.example.com/data",
  "headers": {"X-Custom": "value"},
  "body": {"key": "value"}
}
```

### Basic auth
```json
{
  "method": "GET",
  "url": "https://api.example.com/protected",
  "auth": {"type": "basic", "username": "user", "password": "pass"}
}
```
