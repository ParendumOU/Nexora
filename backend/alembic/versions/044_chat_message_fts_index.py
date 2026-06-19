"""Add GIN index on messages.content for full-text search.

Revision ID: 044
Revises: 043
Create Date: 2026-06-05
"""
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_content_fts "
        "ON messages USING GIN (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.drop_index("idx_messages_content_fts", table_name="messages")
