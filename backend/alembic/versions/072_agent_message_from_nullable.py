"""Make agent_messages.from_agent_id nullable

A message can originate from a chat's default assistant, which has no org-scoped
Agent row — sending one then violated the NOT NULL + FK on from_agent_id, crashing
the tool and looping. Allow NULL ("from the conversation"). Idempotent.

Revision ID: 072
Revises: 071
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def _col(insp, table, name):
    try:
        return next((c for c in insp.get_columns(table) if c["name"] == name), None)
    except Exception:
        return None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "agent_messages" not in set(insp.get_table_names()):
        return
    col = _col(insp, "agent_messages", "from_agent_id")
    if col is not None and col.get("nullable") is False:
        op.alter_column("agent_messages", "from_agent_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "agent_messages" not in set(insp.get_table_names()):
        return
    col = _col(insp, "agent_messages", "from_agent_id")
    if col is not None and col.get("nullable") is True:
        # Best-effort: only re-tighten if no NULLs exist (else leave nullable).
        has_null = bind.execute(sa.text("SELECT 1 FROM agent_messages WHERE from_agent_id IS NULL LIMIT 1")).first()
        if not has_null:
            op.alter_column("agent_messages", "from_agent_id", existing_type=sa.String(length=36), nullable=False)
