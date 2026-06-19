"""marketplace_items table for the skills/tools/agents marketplace.

Revision ID: 036
Revises: 035
Create Date: 2026-05-30
"""
import sqlalchemy as sa
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "marketplace_items" not in existing_tables:
        op.create_table(
            "marketplace_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("slug", sa.String(100), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("item_type", sa.String(50), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("author", sa.String(255), nullable=False, server_default="Nexora"),
            sa.Column("version", sa.String(50), nullable=False, server_default="1.0.0"),
            sa.Column("tags", sa.JSON, nullable=True),
            sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("install_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("icon", sa.String(10), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_marketplace_items_slug", "marketplace_items", ["slug"], unique=True)
        op.create_index("ix_marketplace_items_item_type", "marketplace_items", ["item_type"])


def downgrade() -> None:
    op.drop_index("ix_marketplace_items_item_type", "marketplace_items")
    op.drop_index("ix_marketplace_items_slug", "marketplace_items")
    op.drop_table("marketplace_items")
