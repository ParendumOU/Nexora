"""Add ON DELETE CASCADE to chat FK constraints and indexes for list queries."""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


# (constraint_name, child_table, fk_column, parent_table, parent_column)
_CASCADE_FKS = [
    ("messages_chat_id_fkey",        "messages",         "chat_id",  "chats", "id"),
    ("tasks_chat_id_fkey",           "tasks",            "chat_id",  "chats", "id"),
    ("agent_logs_chat_id_fkey",      "agent_logs",       "chat_id",  "chats", "id"),
    ("chat_participants_chat_id_fkey", "chat_participants", "chat_id", "chats", "id"),
    ("task_steps_task_id_fkey",      "task_steps",       "task_id",  "tasks", "id"),
]

_INDEXES = [
    ("ix_chats_updated_at",   "chats",  "updated_at"),
    ("ix_agents_is_active",   "agents", "is_active"),
    ("ix_agents_updated_at",  "agents", "updated_at"),
]


def upgrade() -> None:
    for name, child, col, parent, pcol in _CASCADE_FKS:
        op.drop_constraint(name, child, type_="foreignkey")
        op.create_foreign_key(name, child, parent, [col], [pcol], ondelete="CASCADE")

    for idx_name, table, col in _INDEXES:
        op.create_index(idx_name, table, [col])


def downgrade() -> None:
    for idx_name, table, col in _INDEXES:
        op.drop_index(idx_name, table_name=table)

    for name, child, col, parent, pcol in _CASCADE_FKS:
        op.drop_constraint(name, child, type_="foreignkey")
        op.create_foreign_key(name, child, parent, [col], [pcol])
