"""Managed (invited-employee) accounts.

An account created via an org invite (invite-first registration) is "managed":
no personal org, tied to exactly one org, cannot switch/create/join/leave orgs.
A normal self-signup keeps its personal org and is not managed.
"""
import uuid

import pytest
from sqlalchemy import select

from src.models.org import Organization


async def _register(client, email, name, org_invite_token=None):
    body = {"email": email, "password": "TestPass123", "full_name": name}
    if org_invite_token:
        body["org_invite_token"] = org_invite_token
    return await client.post("/api/auth/register", json=body)


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "TestPass123"})
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, r.text
    return {"Authorization": f"Bearer {tok}"}


async def _admin_org_and_invite(client, role="member"):
    """Register an admin, create a team org, return (admin_headers, org, invite_token)."""
    await _register(client, "boss@example.com", "Boss")
    admin = await _login(client, "boss@example.com")
    org = (await client.post("/api/orgs", json={"name": "Acme"}, headers=admin)).json()
    inv = (await client.post(f"/api/orgs/{org['id']}/invites",
                             json={"role": role}, headers=admin)).json()
    return admin, org, inv["token"]


@pytest.mark.asyncio
async def test_invite_first_creates_managed_account(client, db):
    admin, org, token = await _admin_org_and_invite(client)

    r = await _register(client, "emp@example.com", "Emp", org_invite_token=token)
    assert r.status_code == 201, r.text

    emp = await _login(client, "emp@example.com")
    me = (await client.get("/api/users/me", headers=emp)).json()
    assert me["is_managed"] is True

    orgs = (await client.get("/api/orgs", headers=emp)).json()
    assert len(orgs) == 1
    assert orgs[0]["id"] == org["id"]
    assert orgs[0]["role"] == "member"
    assert orgs[0]["is_personal"] is False

    # No personal org was created for the managed user.
    owned = (await db.execute(select(Organization).where(Organization.owner_id == me["id"]))).scalars().all()
    assert owned == []


@pytest.mark.asyncio
async def test_normal_signup_is_unmanaged_with_personal_org(client):
    r = await _register(client, "solo@example.com", "Solo")
    assert r.status_code == 201, r.text
    h = await _login(client, "solo@example.com")

    me = (await client.get("/api/users/me", headers=h)).json()
    assert me["is_managed"] is False

    orgs = (await client.get("/api/orgs", headers=h)).json()
    assert len(orgs) == 1
    assert orgs[0]["is_personal"] is True
    assert orgs[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_managed_user_cannot_switch_create_or_leave(client):
    admin, org, token = await _admin_org_and_invite(client)
    await _register(client, "emp@example.com", "Emp", org_invite_token=token)
    emp = await _login(client, "emp@example.com")

    assert (await client.post("/api/orgs/switch", json={"org_id": org["id"]}, headers=emp)).status_code == 403
    assert (await client.post("/api/orgs", json={"name": "Mine"}, headers=emp)).status_code == 403
    assert (await client.post(f"/api/orgs/{org['id']}/leave", headers=emp)).status_code == 403


@pytest.mark.asyncio
async def test_managed_user_cannot_accept_another_invite(client):
    admin, org, token = await _admin_org_and_invite(client)
    await _register(client, "emp@example.com", "Emp", org_invite_token=token)
    emp = await _login(client, "emp@example.com")

    # A second invite (even to the same org) must be refused for a managed user.
    inv2 = (await client.post(f"/api/orgs/{org['id']}/invites",
                              json={"role": "member"}, headers=admin)).json()
    r = await client.post("/api/orgs/accept-invite", json={"token": inv2["token"]}, headers=emp)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invalid_org_invite_token_rejected(client):
    r = await _register(client, "nope@example.com", "Nope", org_invite_token=str(uuid.uuid4()))
    assert r.status_code == 403
