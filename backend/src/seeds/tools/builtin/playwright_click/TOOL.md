# Browser Click

Click element on web page.

## Parameters
- `session_id` (string, required): Active browser session ID
- `selector` (string, required): CSS selector of element to click
- `timeout` (integer, optional): Milliseconds (default: 5000)

## Returns
```json
{ "clicked": true, "selector": ".submit-button" }
```
