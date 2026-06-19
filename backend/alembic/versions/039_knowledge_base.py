"""Add knowledge_bases, knowledge_files, knowledge_chunks tables.

Revision ID: 039
Revises: 038
Create Date: 2026-05-31
"""
import sqlalchemy as sa
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = inspector.get_table_names()

    if "knowledge_bases" not in existing:
        op.create_table(
            "knowledge_bases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_knowledge_bases_org_id", "knowledge_bases", ["org_id"])

    if "knowledge_files" not in existing:
        op.create_table(
            "knowledge_files",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("filename", sa.String(500), nullable=False),
            sa.Column("content_type", sa.String(200), nullable=False, server_default="text/plain"),
            sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_knowledge_files_kb_id", "knowledge_files", ["kb_id"])

    if "knowledge_chunks" not in existing:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("file_id", sa.String(36), sa.ForeignKey("knowledge_files.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chunk_index", sa.Integer, nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("embedding", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_knowledge_chunks_kb_id", "knowledge_chunks", ["kb_id"])
        op.create_index("ix_knowledge_chunks_file_id", "knowledge_chunks", ["file_id"])


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_files")
    op.drop_table("knowledge_bases")
