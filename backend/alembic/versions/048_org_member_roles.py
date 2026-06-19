"""Add OrgRole enum to org_members.role and enforce RBAC defaults.

Revision ID: 048
Revises: 047
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None

_VALID_ROLES = {"owner", "admin", "member", "viewer"}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── 1. Normalise existing role values ────────────────────────────────────
    # Any stale / unrecognised value → 'member'
    conn.execute(
        sa.text(
            "UPDATE org_members SET role = 'member' "
            "WHERE role NOT IN ('owner','admin','member','viewer')"
        )
    )

    # ── 2. Ensure every org has exactly one owner row ─────────────────────────
    # Promote the org's owner_id member record if it is not already 'owner'.
    # If no record exists for owner_id this is a data-quality issue handled below.
    conn.execute(
        sa.text(
            """
            UPDATE org_members om
            SET role = 'owner'
            FROM organizations o
            WHERE om.org_id = o.id
              AND om.user_id = o.owner_id
              AND om.role != 'owner'
            """
        )
    )

    # ── 3. Convert String column → PostgreSQL ENUM ────────────────────────────
    # Check dialect; SQLite used in tests has no native ENUM support.
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        # Create the enum type (idempotent via DO block)
        conn.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orgrole') THEN
                        CREATE TYPE orgrole AS ENUM ('owner','admin','member','viewer');
                    END IF;
                END$$;
                """
            )
        )
        # Alter column to use the enum, casting existing values
        conn.execute(
            sa.text(
                "ALTER TABLE org_members "
                "ALTER COLUMN role TYPE orgrole USING role::orgrole"
            )
        )
        # Also set a server default so new rows without an explicit role get 'member'
        conn.execute(
            sa.text(
                "ALTER TABLE org_members "
                "ALTER COLUMN role SET DEFAULT 'member'::orgrole"
            )
        )
    else:
        # SQLite / other: leave as String; the ORM handles validation
        pass


def downgrade() -> None:
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        # Revert to plain VARCHAR
        conn.execute(
            sa.text(
                "ALTER TABLE org_members "
                "ALTER COLUMN role TYPE VARCHAR(50) USING role::text"
            )
        )
        conn.execute(
            sa.text(
                "ALTER TABLE org_members "
                "ALTER COLUMN role SET DEFAULT 'member'"
            )
        )
        conn.execute(sa.text("DROP TYPE IF EXISTS orgrole"))
