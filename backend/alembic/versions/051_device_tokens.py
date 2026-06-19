"""Add device_tokens table (mobile device pairing).

Revision ID: 051
Revises: 050
Create Date: 2026-06-07
"""
import sqlalchemy as sa
from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    op.create_unique_constraint("uq_device_tokens_token_hash", "device_tokens", ["token_hash"])
    op.create_index("ix_device_tokens_token_hash", "device_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_device_tokens_token_hash", table_name="device_tokens")
    op.drop_constraint("uq_device_tokens_token_hash", "device_tokens", type_="unique")
    op.drop_index("ix_device_tokens_user_id", table_name="device_tokens")
    op.drop_table("device_tokens")
