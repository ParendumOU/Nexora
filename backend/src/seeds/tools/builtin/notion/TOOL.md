# Notion

Read and write Notion pages and databases via the Notion API v1.

## Configuration

Create an integration at https://www.notion.so/my-integrations, copy the Internal Integration Token, and share your pages/databases with it.

```
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Actions

### search
Search pages and databases by title.
```json
{"action": "search", "query": "meeting notes", "limit": 10}
```

### get_page
Get page content (title + text blocks).
```json
{"action": "get_page", "page_id": "page-uuid-or-url"}
```

### create_page
Create a new page inside a parent page or database.
```json
{"action": "create_page", "parent_id": "parent-uuid", "title": "My Page", "content": "Page body text"}
```
Use `parent_type: "database"` (default `"page"`) when parent is a database.

### update_page
Update a page title or properties.
```json
{"action": "update_page", "page_id": "page-uuid", "title": "New Title"}
```
Or archive it: `"archived": true`

### append_blocks
Append text blocks to an existing page.
```json
{"action": "append_blocks", "page_id": "page-uuid", "content": "New paragraph to append"}
```

### query_database
Query a Notion database with optional filter and sort.
```json
{"action": "query_database", "database_id": "db-uuid", "limit": 20}
```
Optional: `"filter": {...}` and `"sorts": [...]` (Notion API filter/sort objects).
