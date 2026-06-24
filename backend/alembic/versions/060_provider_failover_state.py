"""Per-account provider failover health/circuit state (GitLab #216)

Adds durable per-account columns to ``providers`` so multi-account failover is
explicit and observable rather than relying solely on an ephemeral Redis
cooldown key:
  - ``state`` (healthy | cooling | exhausted)
  - ``cooling_until`` (durable skip-until, survives Redis flush/restart)
  - ``consecutive_failures`` (drives the circuit — non-rate errors past the
    configured threshold mark the account exhausted)

Existing rows backfill to the safe healthy / 0 defaults.

Revision ID: 060
Revises: 059
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("state", sa.String(length=20), server_default="healthy", nullable=False),
    )
    op.add_column("providers", sa.Column("cooling_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "providers",
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("providers", "consecutive_failures")
    op.drop_column("providers", "cooling_until")
    op.drop_column("providers", "state")
