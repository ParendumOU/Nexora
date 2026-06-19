"""Backfill messages.agent_id from chats.agent_id for legacy assistant rows.

Historically the sub-agent executor and orchestrator-resume paths saved
assistant messages without `agent_id`, which broke author attribution after
refresh (see GitLab issue #51). The fix populates `agent_id` going forward;
this migration backfills existing rows where:

  - role = 'assistant'
  - agent_id IS NULL
  - the parent chat has a non-null agent_id

Idempotent: re-running has no effect once all rows are backfilled.
"""
from alembic import op


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE messages m
        SET agent_id = c.agent_id
        FROM chats c
        WHERE m.chat_id = c.id
          AND m.role = 'assistant'
          AND m.agent_id IS NULL
          AND c.agent_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Non-reversible: we cannot tell which rows we touched. No-op.
    pass
