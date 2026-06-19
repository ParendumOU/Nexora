"""Add webhook_url and webhook_secret to chats table.

Revision ID: 037
Revises: 036
Create Date: 2026-05-31
"""
import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("chats")}

    if "webhook_url" not in existing_cols:
        op.add_column("chats", sa.Column("webhook_url", sa.String(2048), nullable=True))
    if "webhook_secret" not in existing_cols:
        op.add_column("chats", sa.Column("webhook_secret", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "webhook_secret")
    op.drop_column("chats", "webhook_url")
