"""Add embedding column to agent_memories and project_memories.

Revision ID: 038
Revises: 037
Create Date: 2026-05-31
"""
import sqlalchemy as sa
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table in ("agent_memories", "project_memories"):
        existing = {c["name"] for c in inspector.get_columns(table)}
        if "embedding" not in existing:
            op.add_column(table, sa.Column("embedding", sa.JSON, nullable=True))


def downgrade() -> None:
    for table in ("agent_memories", "project_memories"):
        op.drop_column(table, "embedding")
