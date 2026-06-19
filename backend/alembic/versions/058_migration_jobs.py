"""Add migration columns to backup_jobs (direct instance→instance push).

Adds ``kind``, ``target_url``, ``summary`` so a backup job can also represent a
one-step migration (build a backup, push it into a target instance's import API).

Revision ID: 058
Revises: 057
Create Date: 2026-06-16
"""
import sqlalchemy as sa
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backup_jobs",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="export"),
    )
    op.add_column("backup_jobs", sa.Column("target_url", sa.Text(), nullable=True))
    op.add_column("backup_jobs", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("backup_jobs", "summary")
    op.drop_column("backup_jobs", "target_url")
    op.drop_column("backup_jobs", "kind")
