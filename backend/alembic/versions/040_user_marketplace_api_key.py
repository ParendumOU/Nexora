"""Add marketplace_api_key_enc to users table.

Revision ID: 040
Revises: 039
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("marketplace_api_key_enc", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "marketplace_api_key_enc")
