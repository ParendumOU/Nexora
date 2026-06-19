"""Add oauth_provider and oauth_id columns to users for social login.

Revision ID: 045
Revises: 044
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oauth_provider", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("oauth_id", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_oauth", "users", ["oauth_provider", "oauth_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_oauth", "users", type_="unique")
    op.drop_column("users", "oauth_id")
    op.drop_column("users", "oauth_provider")
