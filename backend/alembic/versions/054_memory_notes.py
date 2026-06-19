"""Add memory_notes + memory_links (agent markdown memory + reference graph).

Revision ID: 054
Revises: 053
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_notes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chat_id", sa.String(length=36), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "path", name="uq_memory_note_org_path"),
    )
    op.create_index("ix_memory_notes_org_id", "memory_notes", ["org_id"])
    op.create_index("ix_memory_notes_agent_id", "memory_notes", ["agent_id"])

    op.create_table(
        "memory_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("src_note_id", sa.String(length=36), sa.ForeignKey("memory_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_note_id", sa.String(length=36), sa.ForeignKey("memory_notes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("via", sa.String(length=20), nullable=False, server_default="wikilink"),
        sa.Column("target_ref", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_links_org_id", "memory_links", ["org_id"])
    op.create_index("ix_memory_links_src", "memory_links", ["src_note_id"])
    op.create_index("ix_memory_links_dst", "memory_links", ["dst_note_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_links_dst", table_name="memory_links")
    op.drop_index("ix_memory_links_src", table_name="memory_links")
    op.drop_index("ix_memory_links_org_id", table_name="memory_links")
    op.drop_table("memory_links")
    op.drop_index("ix_memory_notes_agent_id", table_name="memory_notes")
    op.drop_index("ix_memory_notes_org_id", table_name="memory_notes")
    op.drop_table("memory_notes")
