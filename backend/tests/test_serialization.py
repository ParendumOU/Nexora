"""Unit tests for model serialization helpers (plan/step + marketplace item +
task dict). These convert ORM rows to JSON-safe dicts; they are pure functions
that touch only attribute access + isoformat, so no DB is needed.
"""
import uuid
from datetime import datetime, timezone

import pytest

from src.models.plan import Plan, PlanStep
from src.models.marketplace import MarketplaceItem
from src.api.routers.plans import _plan_dict, _step_dict
from src.api.routers.marketplace import _item_to_dict


NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _make_step(position=0, status="pending"):
    return PlanStep(
        id=str(uuid.uuid4()),
        plan_id="p1",
        position=position,
        title=f"step {position}",
        description="desc",
        status=status,
        note=None,
        task_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


# ── plan / step serialization ───────────────────────────────────────────────


def test_step_dict_shape():
    s = _make_step()
    d = _step_dict(s)
    assert set(d) == {
        "id", "plan_id", "position", "title", "description",
        "status", "note", "task_id", "created_at", "updated_at",
    }
    assert d["created_at"] == NOW.isoformat()


def test_plan_dict_sorts_steps_by_position():
    p = Plan(
        id="p1", chat_id="c1", title="Plan", status="active",
        created_at=NOW, updated_at=NOW, completed_at=None,
    )
    steps = [_make_step(position=2), _make_step(position=0), _make_step(position=1)]
    d = _plan_dict(p, steps=steps)
    positions = [s["position"] for s in d["steps"]]
    assert positions == [0, 1, 2]


def test_plan_dict_completed_at_none_when_unset():
    p = Plan(id="p1", chat_id="c1", title="Plan", status="active",
             created_at=NOW, updated_at=NOW, completed_at=None)
    d = _plan_dict(p, steps=[])
    assert d["completed_at"] is None


def test_plan_dict_completed_at_isoformat_when_set():
    p = Plan(id="p1", chat_id="c1", title="Plan", status="completed",
             created_at=NOW, updated_at=NOW, completed_at=NOW)
    d = _plan_dict(p, steps=[])
    assert d["completed_at"] == NOW.isoformat()


# ── marketplace item serialization ──────────────────────────────────────────


def test_item_to_dict_defaults_and_installed_flag():
    item = MarketplaceItem(
        id="i1", slug="web_search", name="Web Search", item_type="tool",
        description="search the web", author="parendum", version="1.0.0",
        tags=None, is_builtin=True, install_count=42, icon=None,
        created_at=NOW,
    )
    d = _item_to_dict(item, installed=True)
    assert d["type"] == "tool"
    assert d["tags"] == []          # None coerced to []
    assert d["installed"] is True
    assert d["install_count"] == 42
    assert d["created_at"] == NOW.isoformat()


def test_item_to_dict_handles_null_created_at():
    item = MarketplaceItem(
        id="i2", slug="x", name="X", item_type="skill",
        description="", author="a", version="1.0.0", tags=["t"],
        is_builtin=False, install_count=0, icon="🛠", created_at=None,
    )
    d = _item_to_dict(item)
    assert d["created_at"] is None
    assert d["installed"] is False
    assert d["tags"] == ["t"]
