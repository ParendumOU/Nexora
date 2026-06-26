"""Repo provisioning via git-proxy (#242): namespace listing + repo creation.

The external GitHub/GitLab HTTP is mocked (no network); these assert the endpoints
shape requests/responses correctly and stay org-scoped + authenticated.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.api.routers.git_proxy as gp


def _resp(status, payload):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    r.text = str(payload)
    return r


def _client_cm(*, get=None, post=None):
    """Fake httpx.AsyncClient context manager with scripted get/post."""
    c = MagicMock()
    if get is not None:
        c.get = AsyncMock(side_effect=get) if isinstance(get, list) else AsyncMock(return_value=get)
    if post is not None:
        c.post = AsyncMock(side_effect=post) if isinstance(post, list) else AsyncMock(return_value=post)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=c)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def _make_cred(client, auth_headers, provider="github"):
    r = await client.post("/api/git-credentials", headers=auth_headers, json={
        "name": f"{provider}-cred", "provider": provider, "token": "glpat-TESTSECRET",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_namespaces_requires_auth(client):
    r = await client.get("/api/git-proxy/namespaces", params={"credential_id": "x"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_github_namespaces_lists_user_and_orgs(client, auth_headers):
    cred_id = await _make_cred(client, auth_headers, "github")
    gets = [
        _resp(200, {"login": "alice"}),                         # /user
        _resp(200, [{"login": "acme"}, {"login": "globex"}]),   # /user/orgs
    ]
    with patch.object(gp.httpx, "AsyncClient", return_value=_client_cm(get=gets)):
        r = await client.get("/api/git-proxy/namespaces", headers=auth_headers,
                             params={"credential_id": cred_id})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data[0]["kind"] == "user" and "alice" in data[0]["name"]
    kinds = {d["name"]: d["kind"] for d in data}
    assert kinds.get("acme") == "org" and kinds.get("globex") == "org"


@pytest.mark.asyncio
async def test_github_create_repo_personal(client, auth_headers):
    cred_id = await _make_cred(client, auth_headers, "github")
    created = _resp(201, {"clone_url": "https://github.com/alice/proj.git", "default_branch": "main"})
    with patch.object(gp.httpx, "AsyncClient", return_value=_client_cm(post=created)):
        r = await client.post("/api/git-proxy/create-repo", headers=auth_headers, json={
            "credential_id": cred_id, "name": "proj", "private": True,
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repo_url"] == "https://github.com/alice/proj.git"
    assert body["provider"] == "github" and body["default_branch"] == "main"


@pytest.mark.asyncio
async def test_gitlab_create_repo_in_group(client, auth_headers):
    cred_id = await _make_cred(client, auth_headers, "gitlab")
    created = _resp(201, {"http_url_to_repo": "https://gitlab.com/grp/proj.git", "default_branch": "main"})
    with patch.object(gp.httpx, "AsyncClient", return_value=_client_cm(post=created)):
        r = await client.post("/api/git-proxy/create-repo", headers=auth_headers, json={
            "credential_id": cred_id, "name": "proj", "namespace": "42", "private": False,
        })
    assert r.status_code == 200, r.text
    assert r.json()["repo_url"] == "https://gitlab.com/grp/proj.git"


@pytest.mark.asyncio
async def test_create_repo_requires_name(client, auth_headers):
    cred_id = await _make_cred(client, auth_headers, "github")
    r = await client.post("/api/git-proxy/create-repo", headers=auth_headers, json={
        "credential_id": cred_id, "name": "   ",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_repo_propagates_provider_error(client, auth_headers):
    cred_id = await _make_cred(client, auth_headers, "github")
    err = _resp(422, {"message": "name already exists"})
    with patch.object(gp.httpx, "AsyncClient", return_value=_client_cm(post=err)):
        r = await client.post("/api/git-proxy/create-repo", headers=auth_headers, json={
            "credential_id": cred_id, "name": "dup",
        })
    assert r.status_code == 422
