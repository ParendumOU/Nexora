# Browser Fill Form

Fill input field on web page.

## Parameters
- `session_id` (string, required): Active browser session ID
- `selector` (string, required): CSS selector of input element
- `value` (string, required): Text to fill
- `timeout` (integer, optional): Milliseconds (default: 5000)

## Returns
```json
{ "filled": true, "selector": "#email", "value": "user@example.com" }
```
