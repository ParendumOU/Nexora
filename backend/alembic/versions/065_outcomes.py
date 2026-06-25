"""Outcome tracking + decision log (GitLab #236)

Adds the `outcomes` table. Idempotent (startup create_all may create it first).

Revision ID: 065
Revises: 064
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "outcomes" in set(insp.get_table_names()):
        return
    op.create_table(
        "outcomes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(length=20), server_default="outcome", nullable=False, index=True),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="info", nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("metric_name", sa.String(length=120), nullable=True),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("ref_type", sa.String(length=20), nullable=True),
        sa.Column("ref_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="agent", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "outcomes" in set(insp.get_table_names()):
        op.drop_table("outcomes")
