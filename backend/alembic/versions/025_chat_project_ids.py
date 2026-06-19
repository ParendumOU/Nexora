"""Add project_ids JSON column to chats table."""
import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("chats")}
    if "project_ids" not in cols:
        op.add_column("chats", sa.Column("project_ids", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "project_ids")
