"""installed package provenance (marketplace update tracking)

Revision ID: 056
Revises: 055
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installed_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("source_slug", sa.String(length=150), nullable=False),
        sa.Column("origin", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("installed_version", sa.String(length=50), server_default="1.0.0", nullable=False),
        sa.Column("available_version", sa.String(length=50), nullable=True),
        sa.Column("pricing_type", sa.String(length=20), server_default="free", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "item_type", "source_slug", name="uq_installed_pkg_org_type_slug"),
    )
    op.create_index("ix_installed_packages_org_id", "installed_packages", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_installed_packages_org_id", table_name="installed_packages")
    op.drop_table("installed_packages")
