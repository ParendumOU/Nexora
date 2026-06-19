# Read URL

Fetch, parse content of public URL.

## Usage
- Use after `web_search` → read full content of result
- JS-heavy pages: use `playwright_navigate` instead
- Respect robots.txt, rate limits — no hammering same domain
- APIs: prefer `http_request` → raw JSON control

## Example
```tool_calls
[{"name": "read_url", "args": {"url": "https://docs.python.org/3/library/asyncio.html"}}]
```
