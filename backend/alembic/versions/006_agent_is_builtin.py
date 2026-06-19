"""add is_builtin to agents

Revision ID: 006
Revises: 005
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "agents" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("agents")]
        if "is_builtin" not in cols:
            op.add_column(
                "agents",
                sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="false"),
            )


def downgrade() -> None:
    op.drop_column("agents", "is_builtin")
