"""Performance indexes: tasks / schedules / proposals + trigram message search

GitLab #171 (tasks(chat_id,status) — recovery engine scan), #204 (scheduler +
proposals), #175 part b (pg_trgm GIN for ILIKE message/chat search).

All Postgres-specific bits are guarded; on other dialects only the plain b-tree
indexes are created. Idempotent.

Revision ID: 068
Revises: 067
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def _existing_indexes(insp, table) -> set[str]:
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # #171 — recovery engine scans tasks by (chat_id, status) every ~2 min.
    if "tasks" in tables and "ix_tasks_chat_id_status" not in _existing_indexes(insp, "tasks"):
        op.create_index("ix_tasks_chat_id_status", "tasks", ["chat_id", "status"])

    # #204 — scheduler picks due active schedules; proposals list filters by org+status.
    if "schedules" in tables and "ix_schedules_active_next_run" not in _existing_indexes(insp, "schedules"):
        op.create_index("ix_schedules_active_next_run", "schedules", ["is_active", "next_run_at"])
    if "agent_proposals" in tables and "ix_proposals_org_status_created" not in _existing_indexes(insp, "agent_proposals"):
        op.create_index("ix_proposals_org_status_created", "agent_proposals", ["org_id", "status", "created_at"])

    # #175b — full-text-ish ILIKE search uses %term%; a pg_trgm GIN index makes it
    # index-assisted instead of a sequential scan. Postgres only.
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute("CREATE INDEX IF NOT EXISTS ix_messages_content_trgm ON messages USING gin (content gin_trgm_ops)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_chats_title_trgm ON chats USING gin (title gin_trgm_ops)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_chats_title_trgm")
        op.execute("DROP INDEX IF EXISTS ix_messages_content_trgm")
    insp = sa.inspect(bind)
    for tbl, idx in (
        ("agent_proposals", "ix_proposals_org_status_created"),
        ("schedules", "ix_schedules_active_next_run"),
        ("tasks", "ix_tasks_chat_id_status"),
    ):
        try:
            if idx in _existing_indexes(insp, tbl):
                op.drop_index(idx, table_name=tbl)
        except Exception:
            pass
