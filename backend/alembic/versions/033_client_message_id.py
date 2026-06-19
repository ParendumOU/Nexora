"""Add client_message_id to messages for deduplication.

Revision ID: 033
Revises: 032
Create Date: 2026-05-30
"""
import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = [c["name"] for c in inspector.get_columns("messages")]

    if "client_message_id" not in existing_cols:
        op.add_column("messages", sa.Column("client_message_id", sa.String(36), nullable=True))
        # Partial-style unique: enforce only when value is not null (Postgres supports this natively)
        op.create_index(
            "ix_messages_client_message_id",
            "messages",
            ["client_message_id"],
            unique=True,
            postgresql_where=sa.text("client_message_id IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("ix_messages_client_message_id", "messages")
    op.drop_column("messages", "client_message_id")
