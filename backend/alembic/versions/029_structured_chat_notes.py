"""Structured chat_notes table — migrate chats.notes blob to rows.

Revision ID: 029
Revises: 028
Create Date: 2026-05-25
"""
import uuid
import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "chat_notes" not in existing_tables:
        op.create_table(
            "chat_notes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("author", sa.String(200), nullable=True),
            sa.Column("source_chat_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_chat_notes_chat_id", "chat_notes", ["chat_id"])

    # Migrate existing chats.notes blobs → one ChatNote row per chat
    result = conn.execute(
        sa.text("SELECT id, notes FROM chats WHERE notes IS NOT NULL AND notes != ''")
    )
    rows = result.fetchall()
    if rows:
        conn.execute(
            sa.text(
                "INSERT INTO chat_notes (id, chat_id, content, description, author, created_at, updated_at) "
                "VALUES (:id, :chat_id, :content, :description, :author, NOW(), NOW())"
            ),
            [
                {
                    "id": str(uuid.uuid4()),
                    "chat_id": row[0],
                    "content": row[1],
                    "description": "Migrated from legacy notes",
                    "author": "System",
                }
                for row in rows
            ],
        )


def downgrade() -> None:
    op.drop_index("ix_chat_notes_chat_id", "chat_notes")
    op.drop_table("chat_notes")
