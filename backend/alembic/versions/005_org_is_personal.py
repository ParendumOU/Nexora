"""add is_personal to organizations

Revision ID: 005
Revises: 004
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "organizations" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("organizations")]
        if "is_personal" not in cols:
            op.add_column(
                "organizations",
                sa.Column("is_personal", sa.Boolean, nullable=False, server_default="true"),
            )
            # All existing orgs were created at registration → mark as personal
            op.execute("UPDATE organizations SET is_personal = true")


def downgrade() -> None:
    op.drop_column("organizations", "is_personal")
