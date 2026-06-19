"""thread_memories table — shared memory across all chats in a thread.

Revision ID: 031
Revises: 030
Create Date: 2026-05-26
"""
import sqlalchemy as sa
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "thread_memories" not in existing_tables:
        op.create_table(
            "thread_memories",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("root_chat_id", sa.String(36), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id", ondelete="SET NULL"), nullable=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("agent_name", sa.String(200), nullable=True),
            sa.Column("key", sa.String(100), nullable=True),
            sa.Column("type", sa.String(20), nullable=False, server_default="fact"),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("data", sa.JSON, nullable=True),
            sa.Column("tags", sa.JSON, nullable=True, server_default="[]"),
            sa.Column("priority", sa.Integer, nullable=False, server_default="3"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_thread_memories_root_chat_id", "thread_memories", ["root_chat_id"])
        op.create_index("ix_thread_memories_key", "thread_memories", ["key"])


def downgrade() -> None:
    op.drop_index("ix_thread_memories_key", "thread_memories")
    op.drop_index("ix_thread_memories_root_chat_id", "thread_memories")
    op.drop_table("thread_memories")
