"""Outcome tracking + decision log (GitLab #236)."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession


@pytest.mark.asyncio
async def test_outcomes_requires_auth(client):
    assert (await client.get("/api/outcomes")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_empty(client, auth_headers):
    r = await client.get("/api/outcomes", headers=auth_headers)
    assert r.status_code == 200 and isinstance(r.json(), list)


@pytest_asyncio.fixture
async def svc_db(engine, monkeypatch):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("src.core.database.AsyncSessionLocal", factory)
    monkeypatch.setattr("src.services.outcomes.AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_record_and_query(svc_db):
    from src.services import outcomes as svc
    org = "org-1"
    a = await svc.record(org_id=org, subject="Deploy web", kind="outcome", status="success",
                         detail="deployed v1", metric_name="latency_ms", metric_value=42.0,
                         ref_type="goal", ref_id="g1")
    b = await svc.record(org_id=org, subject="Use Postgres", kind="decision", status="info",
                         detail="chosen for pgvector")
    c = await svc.record(org_id=org, subject="Deploy api", kind="outcome", status="failure")
    assert a and b and c

    allr = await svc.query(org_id=org)
    assert len(allr) == 3
    # newest first
    assert allr[0]["subject"] == "Deploy api"

    failures = await svc.query(org_id=org, status="failure")
    assert len(failures) == 1 and failures[0]["subject"] == "Deploy api"

    decisions = await svc.query(org_id=org, kind="decision")
    assert len(decisions) == 1 and decisions[0]["detail"] == "chosen for pgvector"

    deploys = await svc.query(org_id=org, subject_like="deploy")
    assert len(deploys) == 2

    by_ref = await svc.query(org_id=org, ref_id="g1")
    assert len(by_ref) == 1 and by_ref[0]["metric_value"] == 42.0


@pytest.mark.asyncio
async def test_record_guards(svc_db):
    from src.services import outcomes as svc
    assert await svc.record(org_id=None, subject="x") is None      # no org
    assert await svc.record(org_id="o", subject="  ") is None       # empty subject
    # invalid kind/status normalize, don't crash
    oid = await svc.record(org_id="o", subject="y", kind="weird", status="bogus")
    assert oid
    rows = await svc.query(org_id="o")
    assert rows[0]["kind"] == "outcome" and rows[0]["status"] == "info"
