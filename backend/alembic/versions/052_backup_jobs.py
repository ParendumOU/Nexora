"""Add backup_jobs table (full-platform backup export jobs).

Revision ID: 052
Revises: 051
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="instance"),
        sa.Column("org_ids", sa.Text(), nullable=True),
        sa.Column("include_vectors", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backup_jobs")
