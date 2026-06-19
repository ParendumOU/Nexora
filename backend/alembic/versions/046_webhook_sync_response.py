"""Add sync_response and sync_timeout columns to chats table.

Revision ID: 046
Revises: 045
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("chats")}

    if "sync_response" not in existing_cols:
        op.add_column("chats", sa.Column("sync_response", sa.Boolean(), nullable=False, server_default="false"))
    if "sync_timeout" not in existing_cols:
        op.add_column("chats", sa.Column("sync_timeout", sa.Integer(), nullable=False, server_default="10"))


def downgrade() -> None:
    op.drop_column("chats", "sync_timeout")
    op.drop_column("chats", "sync_response")
