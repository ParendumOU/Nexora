"""chat_files table for file upload attachment system.

Revision ID: 030
Revises: 029
Create Date: 2026-05-26
"""
import sqlalchemy as sa
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "chat_files" not in existing_tables:
        op.create_table(
            "chat_files",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
            sa.Column("root_chat_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("original_filename", sa.String(500), nullable=False),
            sa.Column("stored_filename", sa.String(200), nullable=False),
            sa.Column("content_type", sa.String(200), nullable=False, server_default="application/octet-stream"),
            sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_chat_files_root_chat_id", "chat_files", ["root_chat_id"])
        op.create_index("ix_chat_files_chat_id", "chat_files", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_files_root_chat_id", "chat_files")
    op.drop_index("ix_chat_files_chat_id", "chat_files")
    op.drop_table("chat_files")
