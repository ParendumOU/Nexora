# Database Query

Run read-only SQL against configured databases. Supports SELECT, DESCRIBE (PostgreSQL: `\d`), SHOW TABLES, and EXPLAIN.

## Parameters
- `query` (string, required): SQL to execute — SELECT, DESCRIBE, SHOW, or EXPLAIN only
- `db` (string, optional): Named DB key (matches `DB_TOOL_DSN_<KEY>`). Omit to use default `DB_TOOL_DSN`.
- `limit` (integer, optional): Max rows returned (default 100, max 500)

## Returns
```json
{
  "columns": ["id", "name", "email"],
  "rows": [[1, "Alice", "alice@example.com"]],
  "row_count": 1
}
```

## Configuration

Set one or more DSN environment variables:
```
DB_TOOL_DSN=postgresql://user:pass@host:5432/mydb
DB_TOOL_DSN_ANALYTICS=postgresql://readonly:pass@analytics-host/warehouse
DB_TOOL_DSN_SQLITE=sqlite:///path/to/data.db
```

Supported DSN prefixes: `postgresql://`, `postgres://`, `mysql://`, `sqlite:///`

## Safety
- Only SELECT, SHOW, DESCRIBE, EXPLAIN allowed — INSERT/UPDATE/DELETE/DROP rejected before execution
- PostgreSQL and MySQL connections opened in read-only transaction mode
- Results truncated at `limit` rows

## Examples

```json
{"query": "SELECT id, email FROM users WHERE created_at > '2026-01-01' LIMIT 20"}
```

```json
{"query": "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'", "db": "analytics"}
```

```json
{"query": "EXPLAIN SELECT * FROM orders WHERE status = 'pending'"}
```
