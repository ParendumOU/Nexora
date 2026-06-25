"""API key capability scoping (#177) — read/write scope + org restriction."""
import pytest
from sqlalchemy import select

import uuid

from src.models.user import User
from src.models.org import OrgMember, Organization


async def _make_key(client, auth_headers, **body):
    body.setdefault("name", "k")
    resp = await client.post("/api/users/me/api-keys/", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


@pytest.mark.asyncio
async def test_full_key_allows_read_and_write(client, auth_headers):
    key = await _make_key(client, auth_headers)  # no scopes = full
    h = {"Authorization": f"Bearer {key}"}
    assert (await client.get("/api/users/me", headers=h)).status_code == 200
    # write (PATCH) allowed
    assert (await client.patch("/api/users/me", headers=h, json={"full_name": "X"})).status_code == 200


@pytest.mark.asyncio
async def test_readonly_key_blocks_writes(client, auth_headers):
    key = await _make_key(client, auth_headers, scopes=["read"])
    h = {"Authorization": f"Bearer {key}"}
    assert (await client.get("/api/users/me", headers=h)).status_code == 200
    r = await client.patch("/api/users/me", headers=h, json={"full_name": "Y"})
    assert r.status_code == 403
    assert "scope" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invalid_scope_rejected(client, auth_headers):
    resp = await client.post("/api/users/me/api-keys/", headers=auth_headers,
                             json={"name": "k", "scopes": ["delete-everything"]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_org_restriction_rejected_for_nonmember_org(client, auth_headers):
    resp = await client.post("/api/users/me/api-keys/", headers=auth_headers,
                             json={"name": "k", "allowed_org_ids": ["not-my-org"]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_org_scoped_key_blocks_other_org(client, auth_headers, db):
    # Key restricted to a real-but-non-active org → resolving the active org 403s.
    u = (await db.execute(select(User).where(User.email == "fixture@example.com"))).scalar_one()
    # create a real second org + membership for the user
    org2 = Organization(id="org-two", name="Org Two", slug=f"org-two-{uuid.uuid4().hex[:6]}", owner_id=u.id)
    db.add(org2)
    db.add(OrgMember(org_id="org-two", user_id=u.id))
    await db.commit()

    key = await _make_key(client, auth_headers, allowed_org_ids=["org-two"])
    h = {"Authorization": f"Bearer {key}"}
    # active org is the user's personal org (not org-two) → a request needing the
    # active org should be rejected for this key.
    r = await client.get("/api/agents", headers=h)
    assert r.status_code == 403
