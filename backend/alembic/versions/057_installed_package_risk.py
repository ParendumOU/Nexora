"""installed package marketplace trust/risk acknowledgment (GitLab #158)

Records the marketplace liability signal (coarse ``trust_tier`` + ``warning_level``)
at install time plus whether the user explicitly acknowledged the risk of a
low-reputation (elevated/high) package. Existing rows backfill to the safe
"established"/"standard"/not-acknowledged defaults.

Revision ID: 057
Revises: 056
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installed_packages",
        sa.Column("trust_tier", sa.String(length=20), server_default="established", nullable=False),
    )
    op.add_column(
        "installed_packages",
        sa.Column("warning_level", sa.String(length=20), server_default="standard", nullable=False),
    )
    op.add_column(
        "installed_packages",
        sa.Column(
            "risk_acknowledged",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "installed_packages",
        sa.Column("risk_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("installed_packages", "risk_acknowledged_at")
    op.drop_column("installed_packages", "risk_acknowledged")
    op.drop_column("installed_packages", "warning_level")
    op.drop_column("installed_packages", "trust_tier")
