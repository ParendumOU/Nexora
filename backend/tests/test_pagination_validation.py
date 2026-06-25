"""Pagination + input validation hardening:
#167 (user field caps), #198 (proposal status filter), #192 (cron validation),
#195 (notifications paging), #205 (proposals paging)."""
import pytest


# ── #167 PATCH /users/me field length caps ───────────────────────────────────


@pytest.mark.asyncio
async def test_update_me_rejects_oversized_full_name(client, auth_headers):
    resp = await client.patch("/api/users/me", headers=auth_headers,
                              json={"full_name": "x" * 300})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_me_accepts_normal_values(client, auth_headers):
    resp = await client.patch("/api/users/me", headers=auth_headers,
                              json={"full_name": "Jane Doe", "notes": "hello"})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Jane Doe"


# ── #198 proposals status filter validation ──────────────────────────────────


@pytest.mark.asyncio
async def test_proposals_rejects_unknown_status(client, auth_headers):
    resp = await client.get("/api/proposals?status=bogus", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_proposals_accepts_valid_status(client, auth_headers):
    resp = await client.get("/api/proposals?status=pending", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── #205 proposals pagination bounds ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_proposals_limit_out_of_range_rejected(client, auth_headers):
    resp = await client.get("/api/proposals?limit=9999", headers=auth_headers)
    assert resp.status_code == 422


# ── #195 notifications pagination ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notifications_paging_params(client, auth_headers):
    resp = await client.get("/api/notifications/?limit=10&offset=0", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── #192 cron expression validation ──────────────────────────────────────────


def test_validate_cron_rejects_garbage():
    from src.services.scheduler import validate_cron_expr
    with pytest.raises(ValueError):
        validate_cron_expr("not a cron")
    with pytest.raises(ValueError):
        validate_cron_expr("99 99 99 99 99")


def test_validate_cron_accepts_standard():
    from src.services.scheduler import validate_cron_expr
    validate_cron_expr("*/5 * * * *")
    validate_cron_expr("0 9 * * 1")


@pytest.mark.asyncio
async def test_create_schedule_rejects_bad_cron(client, auth_headers):
    resp = await client.post("/api/schedules", headers=auth_headers, json={
        "name": "bad", "prompt": "do it", "cron_expr": "nope nope",
    })
    assert resp.status_code == 422
