"""Permission groups — admin-managed groups with granular permissions.

Covers group CRUD authorization, effective-permission resolution
(``/api/permissions/me``) and route enforcement via ``permission_guard``.
"""
import uuid

import pytest

from src.models.org import OrgMember, OrgRole


async def _register_and_login(client, email: str, name: str) -> dict:
    await client.post("/api/auth/register", json={
        "email": email,
        "password": "TestPass123",
        "full_name": name,
    })
    resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": "TestPass123",
    })
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"Login failed for {email}: {data}"
    return {"Authorization": f"Bearer {token}"}


async def _setup_org_with_member(client, db):
    """Admin (org owner) + a plain member of the admin's org, both scoped to it.
    Membership is inserted directly (the invite flow trips a naive-datetime
    comparison on SQLite). Returns (admin_headers, member_headers, org_id,
    member_user_id)."""
    admin = await _register_and_login(client, "admin@example.com", "Admin User")
    member = await _register_and_login(client, "member@example.com", "Member User")

    orgs = (await client.get("/api/orgs", headers=admin)).json()
    org_id = orgs[0]["id"]

    member_user_id = (await client.get("/api/users/me", headers=member)).json()["id"]
    db.add(OrgMember(id=str(uuid.uuid4()), org_id=org_id,
                     user_id=member_user_id, role=OrgRole.member))
    await db.commit()

    # Switch the member's active org to the shared org.
    r = await client.post("/api/orgs/switch", json={"org_id": org_id}, headers=member)
    assert r.status_code == 200, r.text

    return admin, member, org_id, member_user_id


@pytest.mark.asyncio
async def test_group_crud_requires_admin(client, db):
    admin, member, _org_id, _member_id = await _setup_org_with_member(client, db)

    r = await client.post("/api/permissions/groups",
                          json={"name": "Restricted", "permissions": ["tasks.view"]},
                          headers=member)
    assert r.status_code == 403

    r = await client.post("/api/permissions/groups",
                          json={"name": "Restricted", "permissions": ["tasks.view"]},
                          headers=admin)
    assert r.status_code == 201, r.text
    group = r.json()
    assert group["name"] == "Restricted"
    assert group["permissions"] == ["tasks.view"]

    r = await client.get("/api/permissions/groups", headers=member)
    assert r.status_code == 403

    r = await client.get("/api/permissions/groups", headers=admin)
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_unknown_permission_key_rejected(client, db):
    admin, _member, _org_id, _member_id = await _setup_org_with_member(client, db)
    r = await client.post("/api/permissions/groups",
                          json={"name": "Bad", "permissions": ["nonsense.key"]},
                          headers=admin)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_member_without_group_keeps_full_access(client, db):
    _admin, member, _org_id, _member_id = await _setup_org_with_member(client, db)

    me = (await client.get("/api/permissions/me", headers=member)).json()
    assert me["restricted"] is False
    assert "agents.manage" in me["permissions"]
    assert "ui.advanced_mode" in me["permissions"]

    r = await client.get("/api/agents", headers=member)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_group_restricts_member_and_enforces_routes(client, db):
    admin, member, _org_id, member_id = await _setup_org_with_member(client, db)

    group = (await client.post("/api/permissions/groups",
                               json={"name": "Tasks only", "permissions": ["tasks.view"]},
                               headers=admin)).json()
    r = await client.put(f"/api/permissions/groups/{group['id']}/members",
                         json={"user_ids": [member_id]}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["member_count"] == 1

    me = (await client.get("/api/permissions/me", headers=member)).json()
    assert me["restricted"] is True
    assert me["permissions"] == ["tasks.view"]

    # Granted area passes; everything else is blocked by the guard.
    r = await client.get("/api/tasks", headers=member)
    assert r.status_code == 200
    r = await client.get("/api/agents", headers=member)
    assert r.status_code == 403
    assert "Missing permission" in r.json()["detail"]
    r = await client.post("/api/agents", json={"name": "X"}, headers=member)
    assert r.status_code == 403
    # tasks.view alone does not grant tasks mutations.
    r = await client.post("/api/tasks", json={"title": "X"}, headers=member)
    assert r.status_code == 403

    # The admin is never restricted, even in the same org.
    r = await client.get("/api/agents", headers=admin)
    assert r.status_code == 200
    me_admin = (await client.get("/api/permissions/me", headers=admin)).json()
    assert me_admin["restricted"] is False
    assert "agents.manage" in me_admin["permissions"]


@pytest.mark.asyncio
async def test_manage_grant_implies_view(client, db):
    admin, member, _org_id, member_id = await _setup_org_with_member(client, db)

    group = (await client.post("/api/permissions/groups",
                               json={"name": "Agent admins", "permissions": ["agents.manage"]},
                               headers=admin)).json()
    await client.put(f"/api/permissions/groups/{group['id']}/members",
                     json={"user_ids": [member_id]}, headers=admin)

    me = (await client.get("/api/permissions/me", headers=member)).json()
    assert "agents.view" in me["permissions"]
    assert "agents.manage" in me["permissions"]

    r = await client.get("/api/agents", headers=member)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_union_of_multiple_groups(client, db):
    admin, member, _org_id, member_id = await _setup_org_with_member(client, db)

    g1 = (await client.post("/api/permissions/groups",
                            json={"name": "G1", "permissions": ["tasks.view"]},
                            headers=admin)).json()
    g2 = (await client.post("/api/permissions/groups",
                            json={"name": "G2", "permissions": ["issues.view", "ui.advanced_mode"]},
                            headers=admin)).json()
    await client.put(f"/api/permissions/groups/{g1['id']}/members",
                     json={"user_ids": [member_id]}, headers=admin)
    await client.put(f"/api/permissions/groups/{g2['id']}/members",
                     json={"user_ids": [member_id]}, headers=admin)

    me = (await client.get("/api/permissions/me", headers=member)).json()
    assert set(me["permissions"]) == {"tasks.view", "issues.view", "ui.advanced_mode"}


@pytest.mark.asyncio
async def test_group_delete_restores_default_access(client, db):
    admin, member, _org_id, member_id = await _setup_org_with_member(client, db)

    group = (await client.post("/api/permissions/groups",
                               json={"name": "Temp", "permissions": ["tasks.view"]},
                               headers=admin)).json()
    await client.put(f"/api/permissions/groups/{group['id']}/members",
                     json={"user_ids": [member_id]}, headers=admin)

    r = await client.get("/api/agents", headers=member)
    assert r.status_code == 403

    r = await client.delete(f"/api/permissions/groups/{group['id']}", headers=admin)
    assert r.status_code == 204

    r = await client.get("/api/agents", headers=member)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_group_name_conflict(client, db):
    admin, _member, _org_id, _member_id = await _setup_org_with_member(client, db)
    r = await client.post("/api/permissions/groups",
                          json={"name": "Dup", "permissions": []}, headers=admin)
    assert r.status_code == 201
    r = await client.post("/api/permissions/groups",
                          json={"name": "Dup", "permissions": []}, headers=admin)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_catalog_lists_all_keys(client, db):
    admin, _member, _org_id, _member_id = await _setup_org_with_member(client, db)
    r = await client.get("/api/permissions/catalog", headers=admin)
    assert r.status_code == 200
    keys = {e["key"] for e in r.json()}
    assert "agents.view" in keys
    assert "agents.manage" in keys
    assert "ui.advanced_mode" in keys


@pytest.mark.asyncio
async def test_non_org_member_cannot_be_assigned(client, db):
    admin, _member, _org_id, _member_id = await _setup_org_with_member(client, db)
    outsider = await _register_and_login(client, "outsider@example.com", "Outsider")
    me = (await client.get("/api/users/me", headers=outsider)).json()

    group = (await client.post("/api/permissions/groups",
                               json={"name": "G", "permissions": []}, headers=admin)).json()
    r = await client.put(f"/api/permissions/groups/{group['id']}/members",
                         json={"user_ids": [me["id"]]}, headers=admin)
    assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# Governance — per-user usage limits + capability allowlists
# ══════════════════════════════════════════════════════════════════════════════

def test_merge_limits_rules():
    from src.core.permissions import merge_limits
    assert merge_limits([]) == {}
    # MAX across positive values.
    m = merge_limits([{"token_budget": 100}, {"token_budget": 200}])
    assert m["token_budget"] == 200
    # A group that is unlimited (missing/0) for a dimension wins → unlimited (0).
    m = merge_limits([{"token_budget": 100}, {"token_budget": 0}])
    assert m["token_budget"] == 0
    m = merge_limits([{"max_concurrent_agents": 3}, {}])
    assert m["max_concurrent_agents"] == 0


def test_merge_capabilities_rules():
    from src.core.permissions import merge_capabilities
    assert merge_capabilities([]) == {}
    # Union when every group restricts the dimension.
    m = merge_capabilities([{"agent_ids": ["a"]}, {"agent_ids": ["b"]}])
    assert m["agent_ids"] == ["a", "b"]
    # Any unrestricted (empty) group → dimension unrestricted.
    m = merge_capabilities([{"agent_ids": ["a"]}, {}])
    assert m["agent_ids"] == []
    m = merge_capabilities([{"agent_ids": ["a"]}])
    assert m["agent_ids"] == ["a"]
    # default_chain_id = first non-null.
    m = merge_capabilities([{"default_chain_id": None}, {"default_chain_id": "c2"}])
    assert m["default_chain_id"] == "c2"


def test_capability_allows():
    from src.core.permissions import capability_allows
    assert capability_allows({}, "agent_ids", "x") is True          # unrestricted
    assert capability_allows(None, "agent_ids", "x") is True
    assert capability_allows({"agent_ids": ["a"]}, "agent_ids", "x") is False
    assert capability_allows({"agent_ids": ["a"]}, "agent_ids", "a") is True
    assert capability_allows({"agent_ids": ["a"]}, "agent_ids", None) is True


@pytest.mark.asyncio
async def test_viewer_excluded_from_settings(client, db):
    """A group-less viewer must NOT get settings.view; a group-less member does."""
    admin, member, org_id, _member_id = await _setup_org_with_member(client, db)
    viewer = await _register_and_login(client, "viewer@example.com", "Viewer User")
    viewer_id = (await client.get("/api/users/me", headers=viewer)).json()["id"]
    db.add(OrgMember(id=str(uuid.uuid4()), org_id=org_id,
                     user_id=viewer_id, role=OrgRole.viewer))
    await db.commit()
    await client.post("/api/orgs/switch", json={"org_id": org_id}, headers=viewer)

    me_viewer = (await client.get("/api/permissions/me", headers=viewer)).json()
    assert "settings.view" not in me_viewer["permissions"]
    assert "agents.view" in me_viewer["permissions"]  # still a normal view key

    me_member = (await client.get("/api/permissions/me", headers=member)).json()
    assert "settings.view" in me_member["permissions"]


@pytest.mark.asyncio
async def test_group_accepts_limits_and_capabilities(client, db):
    admin, _member, _org_id, _member_id = await _setup_org_with_member(client, db)
    r = await client.post("/api/permissions/groups", json={
        "name": "Capped",
        "permissions": ["agents.view"],
        "limits": {"token_budget": 1000, "token_window_hours": 1, "max_concurrent_agents": 1},
        "capabilities": {},
    }, headers=admin)
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["limits"]["token_budget"] == 1000
    assert g["limits"]["max_concurrent_agents"] == 1


@pytest.mark.asyncio
async def test_limits_and_capabilities_validation(client, db):
    admin, _member, _org_id, _member_id = await _setup_org_with_member(client, db)
    # Unknown limit key.
    r = await client.post("/api/permissions/groups",
                          json={"name": "B1", "permissions": [], "limits": {"bogus": 1}},
                          headers=admin)
    assert r.status_code == 400
    # Negative limit.
    r = await client.post("/api/permissions/groups",
                          json={"name": "B2", "permissions": [], "limits": {"token_budget": -5}},
                          headers=admin)
    assert r.status_code == 400
    # Agent id not in the org.
    r = await client.post("/api/permissions/groups",
                          json={"name": "B3", "permissions": [],
                                "capabilities": {"agent_ids": [str(uuid.uuid4())]}},
                          headers=admin)
    assert r.status_code == 400
    # Unknown capability key.
    r = await client.post("/api/permissions/groups",
                          json={"name": "B4", "permissions": [],
                                "capabilities": {"nonsense": ["x"]}},
                          headers=admin)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_me_reports_budget_snapshot(client, db):
    admin, member, _org_id, member_id = await _setup_org_with_member(client, db)
    group = (await client.post("/api/permissions/groups", json={
        "name": "Budgeted", "permissions": ["agents.view"],
        "limits": {"token_budget": 5000, "token_window_hours": 24},
    }, headers=admin)).json()
    await client.put(f"/api/permissions/groups/{group['id']}/members",
                     json={"user_ids": [member_id]}, headers=admin)

    me = (await client.get("/api/permissions/me", headers=member)).json()
    assert me["restricted"] is True
    assert me["limits"]["token_budget"] == 5000
    assert me["budget"]["budget"] == 5000
    assert me["budget"]["remaining"] == 5000  # nothing spent yet
    assert me["budget"]["window_hours"] == 24


@pytest.mark.asyncio
async def test_agent_visibility_filtered_by_capability(client, db):
    admin, member, _org_id, member_id = await _setup_org_with_member(client, db)
    a = (await client.post("/api/agents", json={"name": "Allowed"}, headers=admin)).json()
    (await client.post("/api/agents", json={"name": "Hidden"}, headers=admin)).json()

    group = (await client.post("/api/permissions/groups", json={
        "name": "OneAgent", "permissions": ["agents.view"],
        "capabilities": {"agent_ids": [a["id"]]},
    }, headers=admin)).json()
    await client.put(f"/api/permissions/groups/{group['id']}/members",
                     json={"user_ids": [member_id]}, headers=admin)

    visible = (await client.get("/api/agents", headers=member)).json()
    names = {x["name"] for x in visible}
    assert names == {"Allowed"}

    # Admin still sees both (never restricted).
    admin_view = (await client.get("/api/agents", headers=admin)).json()
    assert {"Allowed", "Hidden"}.issubset({x["name"] for x in admin_view})


@pytest.mark.asyncio
async def test_user_budget_summation_window_vs_lifetime(client, db):
    """user_tokens_used sums Message.metadata_ usage over Chat.user_id, window-aware."""
    import uuid as _uuid
    from datetime import datetime, timezone, timedelta
    from src.models.chat import Chat, Message
    from src.services.budget import user_tokens_used

    _admin, member, _org_id, member_id = await _setup_org_with_member(client, db)

    chat_id = str(_uuid.uuid4())
    db.add(Chat(id=chat_id, user_id=member_id, title="t"))
    await db.flush()
    now = datetime.now(timezone.utc)
    # Recent message (within a 1h window) + an old one (outside it).
    db.add(Message(id=str(_uuid.uuid4()), chat_id=chat_id, role="assistant", content="a",
                   metadata_={"usage": {"input_tokens": 100, "output_tokens": 50}},
                   created_at=now))
    db.add(Message(id=str(_uuid.uuid4()), chat_id=chat_id, role="assistant", content="b",
                   metadata_={"usage": {"input_tokens": 1000, "output_tokens": 0}},
                   created_at=now - timedelta(hours=5)))
    await db.commit()

    assert await user_tokens_used(db, member_id, 0) == 1150     # lifetime
    assert await user_tokens_used(db, member_id, 1) == 150      # 1h window only
