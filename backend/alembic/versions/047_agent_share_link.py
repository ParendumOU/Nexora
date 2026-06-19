"""Add share_token and share_enabled columns to agents table.

Revision ID: 047
Revises: 046
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("agents")}

    if "share_token" not in existing_cols:
        op.add_column("agents", sa.Column("share_token", sa.String(64), nullable=True, unique=True))
    if "share_enabled" not in existing_cols:
        op.add_column("agents", sa.Column("share_enabled", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("agents", "share_enabled")
    op.drop_column("agents", "share_token")
