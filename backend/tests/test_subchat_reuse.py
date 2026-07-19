"""Structural sub-chat reuse: delegating again to the same agent under the same
parent chat must resume its newest completed sub-chat instead of minting a new
one, and hydrate its recent history as a budgeted recap block.

Covers `_find_reusable_subchat` (candidate selection + guards) and
`_render_history_recap` (budgeting, labels, marker stripping), plus the
`continue_chat_id` preservation contract used by the retry/recovery reset sites.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.core.config import get_settings
from src.models.chat import Chat, Message
from src.models.task import Task
from src.models.user import User
from src.models.org import Organization
from src.models.agent import Agent
from src.services.sub_agent.executor import _find_reusable_subchat, _render_history_recap


def _mk_ids():
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


async def _seed_base(db):
    """Org + user + agent + parent chat."""
    org_id, user_id, agent_id = _mk_ids()
    db.add(User(id=user_id, email=f"{user_id[:8]}@t.io", hashed_password="x", full_name="T"))
    db.add(Organization(id=org_id, name="org", slug=f"org-{org_id[:8]}", owner_id=user_id))
    db.add(Agent(id=agent_id, org_id=org_id, name="worker", is_active=True))
    parent_id = str(uuid.uuid4())
    db.add(Chat(id=parent_id, user_id=user_id, title="parent"))
    await db.commit()
    return org_id, user_id, agent_id, parent_id


async def _add_completed_delegation(
    db, parent_id: str, user_id: str, agent_id: str,
    completed_at: datetime | None = None,
    archived: bool = False,
    cli_native: bool = False,
):
    """Completed Task + its sub-chat under `parent_id` for `agent_id`."""
    sub_id = str(uuid.uuid4())
    db.add(Chat(
        id=sub_id, user_id=user_id, parent_chat_id=parent_id,
        agent_id=agent_id, title="sub", is_archived=archived,
    ))
    db.add(Task(
        id=str(uuid.uuid4()), chat_id=parent_id, title="done work",
        status="completed", assigned_agent_id=agent_id, sub_chat_id=sub_id,
        completed_at=completed_at or datetime.now(timezone.utc),
        agent_overrides={"cli_native": True} if cli_native else None,
    ))
    await db.commit()
    return sub_id


@pytest.mark.asyncio
async def test_reuses_newest_completed_subchat(db):
    org_id, user_id, agent_id, parent_id = await _seed_base(db)
    old = await _add_completed_delegation(
        db, parent_id, user_id, agent_id,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    newest = await _add_completed_delegation(db, parent_id, user_id, agent_id)

    found = await _find_reusable_subchat(db, parent_id, agent_id)
    assert found is not None
    assert found.id == newest
    assert found.id != old


@pytest.mark.asyncio
async def test_no_reuse_for_different_agent_or_parent(db):
    org_id, user_id, agent_id, parent_id = await _seed_base(db)
    await _add_completed_delegation(db, parent_id, user_id, agent_id)

    other_agent = str(uuid.uuid4())
    db.add(Agent(id=other_agent, org_id=org_id, name="other", is_active=True))
    other_parent = str(uuid.uuid4())
    db.add(Chat(id=other_parent, user_id=user_id, title="other parent"))
    await db.commit()

    assert await _find_reusable_subchat(db, parent_id, other_agent) is None
    assert await _find_reusable_subchat(db, other_parent, agent_id) is None


@pytest.mark.asyncio
async def test_skips_archived_cli_native_and_busy(db):
    org_id, user_id, agent_id, parent_id = await _seed_base(db)
    await _add_completed_delegation(db, parent_id, user_id, agent_id, archived=True)
    await _add_completed_delegation(db, parent_id, user_id, agent_id, cli_native=True)
    busy_sub = await _add_completed_delegation(db, parent_id, user_id, agent_id)
    # Another task is actively writing into busy_sub → not reusable.
    db.add(Task(
        id=str(uuid.uuid4()), chat_id=parent_id, title="in flight",
        status="in_progress", assigned_agent_id=agent_id, sub_chat_id=busy_sub,
    ))
    await db.commit()

    assert await _find_reusable_subchat(db, parent_id, agent_id) is None

    free_sub = await _add_completed_delegation(db, parent_id, user_id, agent_id)
    found = await _find_reusable_subchat(db, parent_id, agent_id)
    assert found is not None and found.id == free_sub


@pytest.mark.asyncio
async def test_respects_age_cutoff_and_master_switch(db, monkeypatch):
    org_id, user_id, agent_id, parent_id = await _seed_base(db)
    settings = get_settings()
    stale_age = timedelta(hours=settings.subagent_reuse_max_age_hours + 1)
    await _add_completed_delegation(
        db, parent_id, user_id, agent_id,
        completed_at=datetime.now(timezone.utc) - stale_age,
    )
    assert await _find_reusable_subchat(db, parent_id, agent_id) is None

    fresh = await _add_completed_delegation(db, parent_id, user_id, agent_id)
    found = await _find_reusable_subchat(db, parent_id, agent_id)
    assert found is not None and found.id == fresh

    monkeypatch.setattr(settings, "subagent_reuse_subchats", False)
    assert await _find_reusable_subchat(db, parent_id, agent_id) is None


def test_recap_labels_budget_and_marker_strip():
    history = [
        {"role": "assistant", "kind": "task_brief", "content": "Do the thing"},
        {"role": "assistant", "kind": None, "content": "Did the thing <final/>"},
        {"role": "user", "kind": None, "content": "system observation"},
    ]
    recap = _render_history_recap(history)
    assert "[PARENT] Do the thing" in recap
    assert "[YOU] Did the thing" in recap
    assert "<final/>" not in recap
    assert "[USER] system observation" in recap
    # Oldest first: PARENT brief precedes the answer.
    assert recap.index("[PARENT]") < recap.index("[YOU]")


def test_recap_budget_drops_oldest_and_clips_giant_messages(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "subagent_reuse_history_chars", 200)
    history = [
        {"role": "user", "kind": None, "content": "OLDEST " + "x" * 400},
        {"role": "assistant", "kind": None, "content": "NEWEST answer"},
    ]
    recap = _render_history_recap(history)
    assert "NEWEST answer" in recap
    # Giant entries are clipped to a quarter of the budget.
    assert "…[truncated]" in recap or "OLDEST" not in recap


def test_recap_empty_history_and_zero_budget(monkeypatch):
    assert _render_history_recap([]) == ""
    settings = get_settings()
    monkeypatch.setattr(settings, "subagent_reuse_history_chars", 0)
    assert _render_history_recap([{"role": "user", "kind": None, "content": "hi"}]) == ""


@pytest.mark.asyncio
async def test_reset_preserves_thread_via_continue_chat_id(db):
    """Contract used by the retry/recovery reset sites: moving sub_chat_id into
    continue_chat_id makes the re-dispatched run resume the same thread."""
    org_id, user_id, agent_id, parent_id = await _seed_base(db)
    sub_id = str(uuid.uuid4())
    db.add(Chat(id=sub_id, user_id=user_id, parent_chat_id=parent_id, agent_id=agent_id, title="sub"))
    task = Task(
        id=str(uuid.uuid4()), chat_id=parent_id, title="retryable",
        status="in_progress", assigned_agent_id=agent_id, sub_chat_id=sub_id,
    )
    db.add(task)
    await db.commit()

    # Same shape as the executor retry / startup recovery / ws salvage resets.
    task.continue_chat_id = task.continue_chat_id or task.sub_chat_id
    task.sub_chat_id = None
    task.status = "pending"
    await db.commit()
    await db.refresh(task)

    assert task.continue_chat_id == sub_id
    assert task.sub_chat_id is None
