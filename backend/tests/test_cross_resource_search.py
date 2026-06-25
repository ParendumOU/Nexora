"""Cross-resource global search (#211) — agents/tools/skills/projects/KBs."""
import uuid

import pytest
from sqlalchemy import select

from src.models.user import User
from src.models.agent import Agent
from src.models.project import Project


async def _org_id(db) -> str:
    u = (await db.execute(select(User).where(User.email == "fixture@example.com"))).scalar_one()
    return u.active_org_id


@pytest.mark.asyncio
async def test_search_finds_agent_by_name(client, auth_headers, db):
    org_id = await _org_id(db)
    db.add(Agent(id=str(uuid.uuid4()), org_id=org_id, name="Zephyr Deploy Bot",
                 description="handles releases"))
    await db.commit()

    resp = await client.get("/api/search?q=Zephyr", headers=auth_headers)
    assert resp.status_code == 200
    hits = resp.json()["results"]
    assert any(h["type"] == "agent" and "Zephyr" in h["title"] for h in hits)


@pytest.mark.asyncio
async def test_search_finds_project_by_description(client, auth_headers, db):
    org_id = await _org_id(db)
    db.add(Project(id=str(uuid.uuid4()), org_id=org_id, name="Apollo",
                   description="quantumwidget migration project"))
    await db.commit()

    resp = await client.get("/api/search?q=quantumwidget", headers=auth_headers)
    assert resp.status_code == 200
    hits = resp.json()["results"]
    assert any(h["type"] == "project" for h in hits)


@pytest.mark.asyncio
async def test_search_is_org_scoped(client, auth_headers, db):
    # An agent in a different org must not leak into results.
    db.add(Agent(id=str(uuid.uuid4()), org_id="some-other-org", name="SecretAgent",
                 description="should not appear"))
    await db.commit()

    resp = await client.get("/api/search?q=SecretAgent", headers=auth_headers)
    assert resp.status_code == 200
    assert not any(h["title"] == "SecretAgent" for h in resp.json()["results"])
