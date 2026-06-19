"""Add is_archived to chats for soft-delete / archive support."""
import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c["name"] for c in inspector.get_columns("chats")]
    if "is_archived" not in existing:
        op.add_column(
            "chats",
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    try:
        op.drop_column("chats", "is_archived")
    except Exception:
        pass
