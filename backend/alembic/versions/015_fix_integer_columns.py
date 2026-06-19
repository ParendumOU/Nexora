"""Fix agents.max_tokens and messages.tokens_used column types from String to Integer."""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agents", "max_tokens",
        existing_type=sa.String(10),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="max_tokens::integer",
    )
    op.alter_column(
        "messages", "tokens_used",
        existing_type=sa.String(20),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="tokens_used::integer",
    )


def downgrade() -> None:
    op.alter_column(
        "agents", "max_tokens",
        existing_type=sa.Integer(),
        type_=sa.String(10),
        existing_nullable=False,
        postgresql_using="max_tokens::varchar",
    )
    op.alter_column(
        "messages", "tokens_used",
        existing_type=sa.Integer(),
        type_=sa.String(20),
        existing_nullable=True,
        postgresql_using="tokens_used::varchar",
    )
