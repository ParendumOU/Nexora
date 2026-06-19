"""add email verification columns to users

Revision ID: b1e3c4d5f6a7
Revises: a3f7b2c91d4e
Create Date: 2026-06-05

"""
from alembic import op
import sqlalchemy as sa

revision = "b1e3c4d5f6a7"
down_revision = "a3f7b2c91d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("verification_token", sa.String(64), nullable=True),
    )
    op.create_index("ix_users_verification_token", "users", ["verification_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_verification_token", table_name="users")
    op.drop_column("users", "verification_token")
    op.drop_column("users", "is_verified")
