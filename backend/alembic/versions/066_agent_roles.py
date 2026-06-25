"""Persistent agent organisation: agent_roles (GitLab #237)

Idempotent (startup create_all may create it first).

Revision ID: 066
Revises: 065
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "agent_roles" in set(insp.get_table_names()):
        return
    op.create_table(
        "agent_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("area", sa.String(length=200), nullable=True),
        sa.Column("escalates_to_agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "agent_roles" in set(insp.get_table_names()):
        op.drop_table("agent_roles")
