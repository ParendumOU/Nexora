# Browser Extract

Extract content from elements on rendered web page.

## Parameters
- `session_id` (string, required): Active browser session ID
- `selector` (string, required): CSS selector to extract from
- `attribute` (string, optional): HTML attribute to extract (e.g. `href`, `src`) — omit for text content
- `all` (boolean, optional): Extract all matching elements (default: false — first only)

## Returns
```json
{ "results": ["extracted text 1", "extracted text 2"] }
```
