# Browser Navigate

Navigate headless browser → URL → return rendered content.

## Parameters
- `url` (string, required): URL to navigate
- `wait_for` (string, optional): CSS selector or event before return — `load`, `networkidle`, or CSS selector
- `timeout` (integer, optional): Milliseconds (default: 30000)

## Returns
```json
{
  "url": "https://example.com",
  "title": "Page Title",
  "content": "Rendered page text..."
}
```
