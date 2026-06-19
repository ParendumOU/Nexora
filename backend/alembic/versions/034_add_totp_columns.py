"""Add TOTP 2FA columns to users table.

Revision ID: 034
Revises: 033
Create Date: 2026-05-30
"""
import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("users")}

    if "totp_secret" not in existing_cols:
        op.add_column("users", sa.Column("totp_secret", sa.Text, nullable=True))
    if "totp_enabled" not in existing_cols:
        op.add_column("users", sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default="false"))
    if "totp_backup_codes" not in existing_cols:
        op.add_column("users", sa.Column("totp_backup_codes", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
