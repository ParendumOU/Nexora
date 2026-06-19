"""Database query tool — read-only SQL against PostgreSQL, MySQL, or SQLite."""
from __future__ import annotations
import os
import re
import asyncio
from src.core.pubsub import broadcast as _broadcast

_MAX_ROWS = 500
_DEFAULT_LIMIT = 100

_ALLOWED_PREFIX_RE = re.compile(
    r'^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN|WITH)\b',
    re.IGNORECASE,
)
_WRITE_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE|CALL|EXEC)\b',
    re.IGNORECASE,
)


def _get_dsn(db_key: str | None) -> str | None:
    if db_key:
        return os.environ.get(f"DB_TOOL_DSN_{db_key.upper()}")
    return os.environ.get("DB_TOOL_DSN")


def _validate_query(sql: str) -> str | None:
    """Return an error string if the query is not read-only, else None."""
    sql = sql.strip()
    if not _ALLOWED_PREFIX_RE.match(sql):
        return "Only SELECT, SHOW, DESCRIBE, EXPLAIN, and WITH (CTE) queries are allowed."
    if _WRITE_RE.search(sql):
        return "Query contains a disallowed write statement (INSERT/UPDATE/DELETE/etc.)."
    return None


async def _query_postgres(dsn: str, sql: str, limit: int) -> dict:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SET TRANSACTION READ ONLY")
        rows = await conn.fetch(f"{sql.rstrip(';')} LIMIT {limit}")
        if not rows:
            return {"columns": [], "rows": [], "row_count": 0}
        columns = list(rows[0].keys())
        data = [list(r.values()) for r in rows]
        # Coerce non-serialisable types to string
        data = [[str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v for v in row] for row in data]
        return {"columns": columns, "rows": data, "row_count": len(data)}
    finally:
        await conn.close()


async def _query_sqlite(path: str, sql: str, limit: int) -> dict:
    import sqlite3

    def _run() -> dict:
        con = sqlite3.connect(path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(f"{sql.rstrip(';')} LIMIT {limit}")
            rows = cur.fetchall()
            if not rows:
                return {"columns": [], "rows": [], "row_count": 0}
            columns = [d[0] for d in cur.description]
            data = [list(r) for r in rows]
            data = [[str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v for v in row] for row in data]
            return {"columns": columns, "rows": data, "row_count": len(data)}
        finally:
            con.close()

    return await asyncio.to_thread(_run)


async def _query_mysql(dsn: str, sql: str, limit: int) -> dict:
    try:
        import aiomysql
    except ImportError:
        return {"error": "MySQL support requires the aiomysql package. Install it and rebuild."}

    # Parse mysql://user:pass@host:port/db
    import re as _re
    m = _re.match(r'mysql://([^:@]+)(?::([^@]*))?@([^:/]+)(?::(\d+))?/(.+)', dsn)
    if not m:
        return {"error": "Invalid MySQL DSN. Expected mysql://user:pass@host:port/db"}
    user, password, host, port, db = m.group(1), m.group(2) or "", m.group(3), int(m.group(4) or 3306), m.group(5)

    conn = await aiomysql.connect(host=host, port=port, user=user, password=password, db=db)
    try:
        async with conn.cursor() as cur:
            await cur.execute("SET TRANSACTION READ ONLY")
            await cur.execute(f"{sql.rstrip(';')} LIMIT {limit}")
            rows = await cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
            data = [list(r) for r in rows]
            data = [[str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v for v in row] for row in data]
            return {"columns": columns, "rows": data, "row_count": len(data)}
    finally:
        conn.close()


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    sql = (args.get("query") or "").strip()
    db_key = args.get("db") or None
    limit = min(int(args.get("limit") or _DEFAULT_LIMIT), _MAX_ROWS)

    if not sql:
        return {"error": "Missing required field: query"}

    err = _validate_query(sql)
    if err:
        return {"error": err}

    dsn = _get_dsn(db_key)
    if not dsn:
        key_hint = f"DB_TOOL_DSN_{db_key.upper()}" if db_key else "DB_TOOL_DSN"
        return {"error": f"No database configured. Set the {key_hint} environment variable."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "database", "label": f"SQL: {sql[:60]}…",
    })

    try:
        dsn_lower = dsn.lower()
        if dsn_lower.startswith(("postgresql://", "postgres://")):
            result = await _query_postgres(dsn, sql, limit)
        elif dsn_lower.startswith("sqlite:///"):
            path = dsn[len("sqlite:///"):]
            result = await _query_sqlite(path, sql, limit)
        elif dsn_lower.startswith("mysql://"):
            result = await _query_mysql(dsn, sql, limit)
        else:
            return {"error": f"Unsupported DSN scheme. Use postgresql://, sqlite:///, or mysql://."}
    except Exception as exc:
        return {"error": str(exc)}

    return {"data": result}
