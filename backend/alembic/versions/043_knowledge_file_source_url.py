"""Add source_url column to knowledge_files for URL-ingested documents.

Revision ID: 043
Revises: b1e3c4d5f6a7
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "043"
down_revision = "b1e3c4d5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = [c["name"] for c in inspector.get_columns("knowledge_files")]
    if "source_url" not in cols:
        op.add_column(
            "knowledge_files",
            sa.Column("source_url", sa.String(2048), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("knowledge_files", "source_url")
