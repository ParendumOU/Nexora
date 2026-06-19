"""agent version history

Revision ID: 050
Revises: 049
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_versions_agent_version",
        "agent_versions",
        ["agent_id", "version_number"],
    )
    op.create_index(
        "ix_agent_versions_agent_id",
        "agent_versions",
        ["agent_id"],
    )


def downgrade():
    op.drop_index("ix_agent_versions_agent_version", table_name="agent_versions")
    op.drop_index("ix_agent_versions_agent_id", table_name="agent_versions")
    op.drop_table("agent_versions")
