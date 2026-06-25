"""Auth hardening: 2FA-pending token + token_version invalidation (#161, #173)."""
import pytest

from src.core.security import create_access_token


@pytest.mark.asyncio
async def test_2fa_pending_token_rejected_on_real_endpoint(client, auth_headers):
    # Mint a 2fa_pending-scoped token for the fixture user; it must NOT grant access.
    me = await client.get("/api/users/me", headers=auth_headers)
    assert me.status_code == 200
    uid = me.json()["id"]
    pending = create_access_token(uid, None, expires_minutes=5, scope="2fa_pending")
    r = await client.get("/api/users/me", headers={"Authorization": f"Bearer {pending}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_stale_token_version_rejected(client, auth_headers, db):
    from sqlalchemy import select
    from src.models.user import User
    me = await client.get("/api/users/me", headers=auth_headers)
    uid = me.json()["id"]
    user = (await db.execute(select(User).where(User.id == uid))).scalar_one()
    # token stamped with the CURRENT tv works
    good = create_access_token(uid, None, token_version=user.token_version or 0)
    assert (await client.get("/api/users/me", headers={"Authorization": f"Bearer {good}"})).status_code == 200
    # a token with an OLD tv (after a bump) is rejected
    stale = create_access_token(uid, None, token_version=(user.token_version or 0) - 1)
    assert (await client.get("/api/users/me", headers={"Authorization": f"Bearer {stale}"})).status_code == 401


@pytest.mark.asyncio
async def test_token_without_tv_still_accepted(client, auth_headers):
    # Legacy / device tokens without a tv claim are not version-checked.
    me = await client.get("/api/users/me", headers=auth_headers)
    uid = me.json()["id"]
    legacy = create_access_token(uid, None)  # no token_version
    assert (await client.get("/api/users/me", headers={"Authorization": f"Bearer {legacy}"})).status_code == 200


@pytest.mark.asyncio
async def test_builtin_skills_requires_auth(client, auth_headers):
    assert (await client.get("/api/skills/builtin")).status_code in (401, 403)
    assert (await client.get("/api/skills/builtin", headers=auth_headers)).status_code == 200
