"""add steps column to workflow runs

Revision ID: 007
Revises: 006
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("agent_workflow_runs")}
    if "steps" not in cols:
        op.add_column("agent_workflow_runs", sa.Column("steps", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("agent_workflow_runs", "steps")
