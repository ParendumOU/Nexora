"""add shared sessions support

Revision ID: 003
Revises: 002
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    table_names = inspector.get_table_names()

    # Add user_id to messages (tracks which human sent each message)
    if "messages" in table_names:
        cols = [c["name"] for c in inspector.get_columns("messages")]
        if "user_id" not in cols:
            op.add_column("messages", sa.Column("user_id", sa.String(36), nullable=True))
            op.create_foreign_key(
                "fk_messages_user_id", "messages", "users", ["user_id"], ["id"]
            )

    # Create chat_participants table
    if "chat_participants" not in table_names:
        op.create_table(
            "chat_participants",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("chat_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("role", sa.String(50), nullable=False, server_default="participant"),
            sa.Column(
                "joined_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_chat_participants_chat_id", "chat_participants", ["chat_id"])
        op.create_index("ix_chat_participants_user_id", "chat_participants", ["user_id"])
        op.create_unique_constraint(
            "uq_chat_participants_chat_user", "chat_participants", ["chat_id", "user_id"]
        )


def downgrade() -> None:
    op.drop_constraint("uq_chat_participants_chat_user", "chat_participants", type_="unique")
    op.drop_index("ix_chat_participants_user_id", table_name="chat_participants")
    op.drop_index("ix_chat_participants_chat_id", table_name="chat_participants")
    op.drop_table("chat_participants")
    op.drop_constraint("fk_messages_user_id", "messages", type_="foreignkey")
    op.drop_column("messages", "user_id")
