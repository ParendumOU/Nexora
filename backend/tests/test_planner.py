"""Backlog planner + agent-org API (GitLab #237)."""
import pytest

from src.services.planner import prioritize_backlog


def test_orders_by_priority_then_age():
    items = [
        {"id": "a", "priority": 1, "created_at": "2026-01-02", "status": "pending"},
        {"id": "b", "priority": 3, "created_at": "2026-01-03", "status": "pending"},
        {"id": "c", "priority": 3, "created_at": "2026-01-01", "status": "pending"},
    ]
    plan = [i["id"] for i in prioritize_backlog(items)["plan"]]
    assert plan == ["c", "b", "a"]  # pri3 oldest first (c before b), then pri1


def test_done_items_excluded():
    items = [
        {"id": "a", "priority": 1, "status": "completed"},
        {"id": "b", "priority": 1, "status": "pending"},
    ]
    plan = [i["id"] for i in prioritize_backlog(items)["plan"]]
    assert plan == ["b"]


def test_blocked_held_out():
    items = [
        {"id": "a", "priority": 1, "status": "pending"},
        {"id": "b", "priority": 5, "status": "pending", "blocked_by": ["a"]},
    ]
    res = prioritize_backlog(items)
    assert [i["id"] for i in res["plan"]] == ["a"]
    assert len(res["blocked"]) == 1 and res["blocked"][0]["id"] == "b"
    assert res["blocked"][0]["_waiting_on"] == ["a"]


def test_blocker_done_unblocks():
    items = [
        {"id": "a", "priority": 1, "status": "completed"},
        {"id": "b", "priority": 5, "status": "pending", "blocked_by": ["a"]},
    ]
    res = prioritize_backlog(items)
    assert [i["id"] for i in res["plan"]] == ["b"] and res["blocked"] == []


def test_capacity_caps_plan():
    items = [{"id": str(i), "priority": i, "status": "pending"} for i in range(5)]
    res = prioritize_backlog(items, capacity=2)
    assert len(res["plan"]) == 2


@pytest.mark.asyncio
async def test_org_routes_auth_and_empty(client, auth_headers):
    assert (await client.get("/api/org/roles")).status_code in (401, 403)
    r = await client.get("/api/org/roles", headers=auth_headers)
    assert r.status_code == 200 and isinstance(r.json(), list)
    b = await client.get("/api/org/backlog", headers=auth_headers)
    assert b.status_code == 200 and "plan" in b.json() and "blocked" in b.json()
