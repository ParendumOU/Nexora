"""Autonomy dispatch: goals.chat_id host chat (GitLab #234)

Adds a nullable `goals.chat_id` — the chat that hosts autonomous milestone work
(created on first dispatch). Idempotent (guarded) since the backend's startup
`create_all` may add the column before this runs.

Revision ID: 062
Revises: 061
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("goals")}
    if "chat_id" not in cols:
        op.add_column("goals", sa.Column("chat_id", sa.String(length=36), nullable=True))
    fks = {fk.get("name") for fk in insp.get_foreign_keys("goals")}
    if "fk_goals_chat_id" not in fks:
        op.create_foreign_key("fk_goals_chat_id", "goals", "chats", ["chat_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    fks = {fk.get("name") for fk in insp.get_foreign_keys("goals")}
    if "fk_goals_chat_id" in fks:
        op.drop_constraint("fk_goals_chat_id", "goals", type_="foreignkey")
    cols = {c["name"] for c in insp.get_columns("goals")}
    if "chat_id" in cols:
        op.drop_column("goals", "chat_id")
