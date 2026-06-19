"""Add columns that exist in models but were never migrated."""
import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

# (table, column, Column definition)
_MISSING = [
    ("tasks",  "continue_chat_id",         sa.Column("continue_chat_id",         sa.String(36), nullable=True)),
    ("tasks",  "model_profile_id",          sa.Column("model_profile_id",          sa.String(36), nullable=True)),
    ("tasks",  "created_after_message_id",  sa.Column("created_after_message_id",  sa.String(36), nullable=True)),
    ("chats",  "direct_provider_id",        sa.Column("direct_provider_id",        sa.String(36), nullable=True)),
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table, col_name, col_def in _MISSING:
        if table not in inspector.get_table_names():
            continue
        existing = [c["name"] for c in inspector.get_columns(table)]
        if col_name not in existing:
            op.add_column(table, col_def)

    # FK constraints for new columns (only if column was just added)
    # Use raw DDL so missing-column errors don't abort the whole migration
    try:
        op.create_foreign_key(
            "tasks_created_after_message_id_fkey",
            "tasks", "messages",
            ["created_after_message_id"], ["id"],
            ondelete="SET NULL",
        )
    except Exception:
        pass

    try:
        op.create_foreign_key(
            "chats_direct_provider_id_fkey",
            "chats", "providers",
            ["direct_provider_id"], ["id"],
            ondelete="SET NULL",
        )
    except Exception:
        pass


def downgrade() -> None:
    for table, col_name, _ in _MISSING:
        try:
            op.drop_column(table, col_name)
        except Exception:
            pass
