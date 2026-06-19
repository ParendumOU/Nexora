"""Add notes column to chats table."""
import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("chats")}
    if "notes" not in cols:
        op.add_column("chats", sa.Column("notes", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "notes")
