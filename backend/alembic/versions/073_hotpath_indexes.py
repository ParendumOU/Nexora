"""Hot-path composite indexes: messages / chats / schedule_runs

Audit follow-up. Adds the composite indexes the per-turn message load, the chat
sidebar list, the archival sweep, and per-schedule run history rely on but only
had single-column coverage for:

  - messages(chat_id, created_at)      — every history load filters chat_id then
    ORDER BY created_at; the single-col ix_messages_chat_id left a sort.
  - chats(parent_chat_id, is_archived, updated_at) — the archival sweep and the
    sidebar list filter parent scope + is_archived and order by updated_at;
    is_archived was entirely unindexed.
  - chats(user_id, is_archived, updated_at) — the top-level sidebar list.
  - schedule_runs(schedule_id, started_at) — per-schedule run history / latest-run.

Postgres builds these CONCURRENTLY (no long write-lock on a live table); other
dialects (sqlite tests) create them inline. Idempotent.

Revision ID: 073
Revises: 072
Create Date: 2026-07-12
"""
import sqlalchemy as sa
from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


# (index name, table, columns)
_INDEXES = [
    ("ix_messages_chat_created", "messages", ["chat_id", "created_at"]),
    ("ix_chats_parent_archived_updated", "chats", ["parent_chat_id", "is_archived", "updated_at"]),
    ("ix_chats_user_archived_updated", "chats", ["user_id", "is_archived", "updated_at"]),
    ("ix_schedule_runs_sched_started", "schedule_runs", ["schedule_id", "started_at"]),
]


def _existing_indexes(insp, table) -> set[str]:
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    is_pg = bind.dialect.name == "postgresql"

    for name, table, cols in _INDEXES:
        if table not in tables or name in _existing_indexes(insp, table):
            continue
        if is_pg:
            # CONCURRENTLY can't run inside a transaction; alembic wraps upgrade() in
            # one, so commit first and use autocommit for the DDL.
            col_sql = ", ".join(cols)
            with op.get_context().autocommit_block():
                op.execute(
                    f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({col_sql})'
                )
        else:
            op.create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_pg = bind.dialect.name == "postgresql"
    for name, table, _cols in reversed(_INDEXES):
        try:
            if is_pg:
                with op.get_context().autocommit_block():
                    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            elif name in _existing_indexes(insp, table):
                op.drop_index(name, table_name=table)
        except Exception:
            pass
