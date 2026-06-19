"""env variables (org + user scoped) for tool credentials

Revision ID: 055
Revises: 054
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environment_variables",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("value_enc", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "org_id", "user_id", "name", name="uq_env_scope_owner_name"),
    )
    op.create_index("ix_env_org_key", "environment_variables", ["org_id", "key"])
    op.create_index("ix_env_user_key", "environment_variables", ["user_id", "key"])


def downgrade() -> None:
    op.drop_index("ix_env_user_key", table_name="environment_variables")
    op.drop_index("ix_env_org_key", table_name="environment_variables")
    op.drop_table("environment_variables")
