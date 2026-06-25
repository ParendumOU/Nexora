"""Chat-file folders: chat_files.folder for the thread file explorer (#3)

Adds a nullable-with-default `folder` so agent deliverables can be organized into
a folder tree within the thread's directory. Idempotent (startup create_all may add
it first).

Revision ID: 063
Revises: 062
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chat_files")}
    if "folder" not in cols:
        op.add_column("chat_files", sa.Column("folder", sa.String(length=500), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chat_files")}
    if "folder" in cols:
        op.drop_column("chat_files", "folder")
