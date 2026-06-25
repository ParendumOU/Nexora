"""Schedule max_concurrency + timeout_minutes (GitLab #207)

Idempotent.

Revision ID: 069
Revises: 068
Create Date: 2026-06-25
"""
import sqlalchemy as sa
from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def _cols(insp, table) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "schedules" not in set(insp.get_table_names()):
        return
    cols = _cols(insp, "schedules")
    if "max_concurrency" not in cols:
        op.add_column("schedules", sa.Column("max_concurrency", sa.Integer(), server_default="1", nullable=False))
    if "timeout_minutes" not in cols:
        op.add_column("schedules", sa.Column("timeout_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = _cols(insp, "schedules")
    if "timeout_minutes" in cols:
        op.drop_column("schedules", "timeout_minutes")
    if "max_concurrency" in cols:
        op.drop_column("schedules", "max_concurrency")
