"""remove workflows tables

Revision ID: a3f7b2c91d4e
Revises: 040
Create Date: 2026-06-05

"""
from alembic import op
import sqlalchemy as sa

revision = "a3f7b2c91d4e"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("agent_workflow_runs")
    op.drop_table("agent_workflows")


def downgrade() -> None:
    # Not restoring removed feature
    pass
