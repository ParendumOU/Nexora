"""Create agent_messages table for peer-to-peer agent communication."""
import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "agent_messages" not in existing_tables:
        op.create_table(
            "agent_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("from_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False, index=True),
            sa.Column("to_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False, index=True),
            sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), nullable=False, index=True),
            sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("reply_to_id", sa.String(36), sa.ForeignKey("agent_messages.id"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("reply_body", sa.Text(), nullable=True),
            sa.Column("mode", sa.String(10), nullable=False, server_default="sync"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("agent_messages")
