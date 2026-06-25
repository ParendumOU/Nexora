"""Human-in-the-loop tool approvals (GitLab #235)

Adds the `tool_approvals` table backing the approval gate. Idempotent (startup
create_all may create it first).

Revision ID: 064
Revises: 063
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "tool_approvals" in set(insp.get_table_names()):
        return
    op.create_table(
        "tool_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("chat_id", sa.String(length=36), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("agent_name", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=True),
        sa.Column("risk_tier", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False, index=True),
        sa.Column("decided_by", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "tool_approvals" in set(insp.get_table_names()):
        op.drop_table("tool_approvals")
