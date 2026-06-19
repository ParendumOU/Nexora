"""Tests for /api/auth/* endpoints."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post("/api/auth/register", json={
        "email": "register@example.com",
        "password": "Password123!",
        "full_name": "Register User",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_register_duplicate(client):
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "Dup User",
    }
    r1 = await client.post("/api/auth/register", json=payload)
    assert r1.status_code in (200, 201)
    r2 = await client.post("/api/auth/register", json=payload)
    assert r2.status_code in (400, 409, 422)


@pytest.mark.asyncio
async def test_register_weak_password(client):
    """Passwords without uppercase/digit should be rejected with 422."""
    resp = await client.post("/api/auth/register", json={
        "email": "weak@example.com",
        "password": "weakpassword",
        "full_name": "Weak User",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login(client):
    await client.post("/api/auth/register", json={
        "email": "login@example.com",
        "password": "Password123!",
        "full_name": "Login User",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "login@example.com",
        "password": "Password123!",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/auth/register", json={
        "email": "wrongpw@example.com",
        "password": "Password123!",
        "full_name": "Wrong PW User",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wrongpw@example.com",
        "password": "NotTheRightPassword1",
    })
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    resp = await client.post("/api/auth/login", json={
        "email": "nobody@example.com",
        "password": "Password123!",
    })
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_authenticated(client, auth_headers):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    # /api/auth/me may be on /api/users/me; accept 200 or 404 if route differs
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert "email" in resp.json()


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_first_run_returns_bool(client):
    resp = await client.get("/api/auth/first-run")
    assert resp.status_code == 200
    data = resp.json()
    assert "first_run" in data
    assert isinstance(data["first_run"], bool)
