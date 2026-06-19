# Web Search

Search web for current info.

## Usage
- Specific queries — include relevant keywords, context
- Follow up with `read_url` → full content of promising results
- Time-sensitive queries: add current year or "latest"
- Cross-reference multiple results before drawing conclusions

## Example
```tool_calls
[{"name": "web_search", "args": {"query": "FastAPI async SQLAlchemy best practices 2025"}}]
```
