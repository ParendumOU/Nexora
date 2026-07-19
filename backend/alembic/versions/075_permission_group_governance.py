"""Permission group governance — per-user usage limits + capability allowlists

Adds two JSON columns to permission_groups:
  - limits: token budget (total or per rolling window), max concurrent agents,
    max provider accounts. Empty dict / 0 = unlimited.
  - capabilities: allowlists of agent_ids / skill_keys / tool_keys / persona_ids /
    provider_ids / chain_ids the assigned users may see and use, plus a forced
    default_chain_id. Empty list = unrestricted.

Both default to an empty object so existing groups keep unrestricted behaviour.
Idempotent.

Revision ID: 075
Revises: 074
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "permission_groups" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("permission_groups")}
    if "limits" not in cols:
        op.add_column(
            "permission_groups",
            sa.Column("limits", sa.JSON(), nullable=False, server_default="{}"),
        )
    if "capabilities" not in cols:
        op.add_column(
            "permission_groups",
            sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "permission_groups" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("permission_groups")}
    if "capabilities" in cols:
        op.drop_column("permission_groups", "capabilities")
    if "limits" in cols:
        op.drop_column("permission_groups", "limits")
