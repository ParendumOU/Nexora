"""Provider availability snapshot + cooling exposure."""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select


async def _org_id(db, email="fixture@example.com"):
    from src.models.user import User
    from src.models.org import OrgMember
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    m = (await db.execute(select(OrgMember).where(OrgMember.user_id == user.id))).scalars().first()
    return m.org_id


@pytest.mark.asyncio
async def test_availability_reports_cooling_and_usable(client, auth_headers, db):
    from src.models.provider import Provider
    org_id = await _org_id(db)
    healthy = Provider(id=str(uuid.uuid4()), org_id=org_id, name="Live", provider_type="openai",
                       is_active=True, state="healthy")
    cooling = Provider(id=str(uuid.uuid4()), org_id=org_id, name="Limited", provider_type="opencode-go",
                       is_active=True, state="cooling",
                       cooling_until=datetime.now(timezone.utc) + timedelta(hours=2, minutes=16),
                       last_error="GoUsageLimitError")
    db.add_all([healthy, cooling])
    await db.commit()

    r = await client.get("/api/providers/availability", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usable_count"] == 1
    assert body["cooling_count"] == 1
    assert body["any_usable"] is True

    by_name = {a["name"]: a for a in body["accounts"]}
    assert by_name["Live"]["available"] is True
    lim = by_name["Limited"]
    assert lim["available"] is False and lim["cooling"] is True
    assert 7000 < lim["remaining_seconds"] <= 2 * 3600 + 16 * 60
    assert "h" in lim["remaining_human"]


@pytest.mark.asyncio
async def test_list_providers_includes_cooling_remaining(client, auth_headers, db):
    from src.models.provider import Provider
    org_id = await _org_id(db)
    db.add(Provider(id=str(uuid.uuid4()), org_id=org_id, name="C", provider_type="openai",
                    is_active=True, state="cooling",
                    cooling_until=datetime.now(timezone.utc) + timedelta(minutes=30)))
    await db.commit()

    r = await client.get("/api/providers", headers=auth_headers)
    assert r.status_code == 200
    rec = next(p for p in r.json() if p["name"] == "C")
    assert rec["cooling_remaining_seconds"] > 1500


@pytest.mark.asyncio
async def test_availability_summary_quiet_when_all_healthy(client, auth_headers, db):
    from src.services.agent_context.providers import provider_availability_summary
    from src.models.provider import Provider
    org_id = await _org_id(db)
    db.add(Provider(id=str(uuid.uuid4()), org_id=org_id, name="OK", provider_type="openai",
                    is_active=True, state="healthy"))
    await db.commit()
    # No cooling accounts → empty summary (don't waste agent tokens saying all is fine).
    assert await provider_availability_summary(org_id, db=db) == ""


@pytest.mark.asyncio
async def test_availability_summary_lists_cooling(client, auth_headers, db):
    from src.services.agent_context.providers import provider_availability_summary
    from src.models.provider import Provider
    org_id = await _org_id(db)
    db.add_all([
        Provider(id=str(uuid.uuid4()), org_id=org_id, name="Live", provider_type="openai",
                 is_active=True, state="healthy"),
        Provider(id=str(uuid.uuid4()), org_id=org_id, name="Limited", provider_type="opencode-go",
                 is_active=True, state="cooling",
                 cooling_until=datetime.now(timezone.utc) + timedelta(hours=1)),
    ])
    await db.commit()
    summary = await provider_availability_summary(org_id, db=db)
    assert "Provider availability" in summary
    assert "Live" in summary and "Limited" in summary
    assert "cooling" in summary.lower()
