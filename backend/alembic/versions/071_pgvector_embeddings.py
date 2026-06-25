"""pgvector ANN columns + indexes for semantic search (GitLab #201)

Adds a native `vector(1536)` column alongside the existing JSON `embedding` on
knowledge_chunks (and the two memory tables), backfills it from the JSON values
that are the right dimension, and builds an ivfflat cosine index so KB / memory
search can run as an indexed ANN query instead of a full Python-side cosine scan.

Postgres-only and fully guarded: on SQLite (the unit suite) and on a Postgres
without the `vector` extension available, this is a no-op and the app keeps using
the JSON column + Python cosine fallback. 1536 = text-embedding-3-small.

Revision ID: 071
Revises: 070
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None

_DIM = 1536
# (table, json_embedding_column)
_TARGETS = [
    ("knowledge_chunks", "embedding"),
    ("agent_memory", "embedding"),
    ("project_memory", "embedding"),
]


def _has_vector(bind) -> bool:
    try:
        row = bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name='vector'")).first()
        return row is not None
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _has_vector(bind):
        # Extension not installable on this server — leave JSON path in place.
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    for table, json_col in _TARGETS:
        if table not in tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "embedding_vec" not in cols:
            op.execute(f"ALTER TABLE {table} ADD COLUMN embedding_vec vector({_DIM})")
        # Backfill from existing JSON embeddings that match the fixed dimension.
        # The JSON array text (e.g. "[0.1, 0.2, ...]") is a valid vector literal.
        op.execute(
            f"""
            UPDATE {table}
               SET embedding_vec = ({json_col}#>>'{{}}')::vector
             WHERE embedding_vec IS NULL
               AND {json_col} IS NOT NULL
               AND jsonb_array_length(CASE
                     WHEN jsonb_typeof({json_col}::jsonb) = 'array' THEN {json_col}::jsonb
                     ELSE '[]'::jsonb END) = {_DIM}
            """
        )
        # ivfflat cosine index. lists=100 is fine for small/medium corpora.
        idx = f"ix_{table}_embedding_vec"
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON {table} "
            f"USING ivfflat (embedding_vec vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table, _ in _TARGETS:
        if table not in tables:
            continue
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_vec")
        cols = {c["name"] for c in insp.get_columns(table)}
        if "embedding_vec" in cols:
            op.execute(f"ALTER TABLE {table} DROP COLUMN embedding_vec")
