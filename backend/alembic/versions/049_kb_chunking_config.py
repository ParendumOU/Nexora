"""Add chunking configuration columns to knowledge_bases table.

Revision ID: 049
Revises: 048
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("chunk_strategy", sa.String(20), nullable=False, server_default="fixed"),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("chunk_size", sa.Integer, nullable=False, server_default="512"),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("chunk_overlap", sa.Integer, nullable=False, server_default="50"),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "chunk_overlap")
    op.drop_column("knowledge_bases", "chunk_size")
    op.drop_column("knowledge_bases", "chunk_strategy")
