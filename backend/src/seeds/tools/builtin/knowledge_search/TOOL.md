# Knowledge Search

Semantic search across org knowledge bases. Use this to retrieve relevant context from uploaded documents before answering questions.

## Parameters
- `query` (string, required): Natural language search query
- `kb_id` (string, optional): Restrict to a specific knowledge base ID. Omit to search all org KBs.
- `top_k` (integer, optional): Max chunks to return (default 5, max 20)

## Returns
```json
[
  {
    "kb_id": "uuid",
    "kb_name": "Product Docs",
    "file_id": "uuid",
    "filename": "api-reference.md",
    "content": "...relevant chunk...",
    "score": 0.87,
    "chunk_index": 3
  }
]
```

## Example
```json
{"query": "how to authenticate with the API", "kb_id": "my-kb-uuid", "top_k": 5}
```
