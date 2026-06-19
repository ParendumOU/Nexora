# Web Scrape

Fetch + extract readable text from public web page.

## Parameters
- `url` (string, required): URL to scrape
- `selector` (string, optional): CSS selector → extract specific element
- `timeout` (integer, optional): Seconds (default: 15)

## Returns
```json
{
  "url": "https://example.com",
  "title": "Page Title",
  "text": "Extracted plain text content..."
}
```
