"""agent_proposals table

Revision ID: 027
Revises: 026
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    if "agent_proposals" in inspect(conn).get_table_names():
        return

    op.create_table(
        "agent_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("agent_name", sa.String(255), nullable=True),
        sa.Column("proposal_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("execution_result", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_proposals_org_id", "agent_proposals", ["org_id"])
    op.create_index("ix_agent_proposals_status", "agent_proposals", ["status"])


def downgrade() -> None:
    op.drop_table("agent_proposals")
