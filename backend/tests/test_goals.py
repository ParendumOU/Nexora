"""Goals API + roll-up (GitLab #232, Autonomy Layer)."""
import pytest


@pytest.mark.asyncio
async def test_goals_requires_auth(client):
    resp = await client.get("/api/goals")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_list_get_goal(client, auth_headers):
    created = await client.post("/api/goals", headers=auth_headers, json={
        "title": "Ship the autonomy layer", "success_criteria": "epic #238 closed",
        "priority": 5,
    })
    assert created.status_code == 201, created.text
    gid = created.json()["id"]
    assert created.json()["status"] == "active"
    assert created.json()["progress"] == 0

    lst = await client.get("/api/goals", headers=auth_headers)
    assert lst.status_code == 200
    assert any(g["id"] == gid for g in lst.json())

    got = await client.get(f"/api/goals/{gid}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["milestones"] == []


@pytest.mark.asyncio
async def test_milestone_rollup_progress_and_completion(client, auth_headers):
    gid = (await client.post("/api/goals", headers=auth_headers, json={"title": "G"})).json()["id"]
    m1 = (await client.post(f"/api/goals/{gid}/milestones", headers=auth_headers, json={"title": "M1"})).json()["id"]
    m2 = (await client.post(f"/api/goals/{gid}/milestones", headers=auth_headers, json={"title": "M2"})).json()["id"]

    # one of two done → 50%, goal still active
    await client.patch(f"/api/goals/{gid}/milestones/{m1}", headers=auth_headers, json={"status": "done"})
    g = (await client.get(f"/api/goals/{gid}", headers=auth_headers)).json()
    assert g["progress"] == 50 and g["status"] == "active"

    # both done → 100%, goal auto-completes
    await client.patch(f"/api/goals/{gid}/milestones/{m2}", headers=auth_headers, json={"status": "done"})
    g = (await client.get(f"/api/goals/{gid}", headers=auth_headers)).json()
    assert g["progress"] == 100 and g["status"] == "completed" and g["completed_at"]


@pytest.mark.asyncio
async def test_update_and_delete_goal(client, auth_headers):
    gid = (await client.post("/api/goals", headers=auth_headers, json={"title": "tmp"})).json()["id"]
    upd = await client.patch(f"/api/goals/{gid}", headers=auth_headers, json={"status": "blocked", "priority": 9})
    assert upd.status_code == 200 and upd.json()["status"] == "blocked" and upd.json()["priority"] == 9
    dele = await client.delete(f"/api/goals/{gid}", headers=auth_headers)
    assert dele.status_code == 204
    assert (await client.get(f"/api/goals/{gid}", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_goal_not_found(client, auth_headers):
    assert (await client.get("/api/goals/00000000-0000-0000-0000-000000000000", headers=auth_headers)).status_code == 404


def test_goal_agent_tools_are_executable_and_always_allowed():
    # The 5 inline goal tools must resolve to a handler and be coordination tools
    # (always-allowed) so any orchestrator can manage objectives.
    from src.services.agent_tools import is_executable_tool
    from src.services.agent_tools.tool_permissions import _always_allowed
    allowed = _always_allowed()
    for t in ("goal_create", "goal_update", "milestone_add", "milestone_status", "goal_read"):
        assert is_executable_tool(t) is True, f"{t} not executable"
        assert t in allowed, f"{t} not always-allowed"
