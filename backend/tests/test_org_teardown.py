"""Unit tests for org deletion teardown (wipe vs reassign).

Covers src/services/org_teardown.py:
  - expand_wipe() dependency closure
  - teardown_org() reassigns kept categories to the target org
  - teardown_org() wipes selected categories (and their dependents)
"""
import uuid

import pytest
from sqlalchemy import text

from src.services.org_teardown import expand_wipe, teardown_org
from src.models.org import Organization
from src.models.persona import Persona
from src.models.agent import Agent


def test_expand_wipe_closure():
    assert expand_wipe(set()) == set()
    assert expand_wipe({"catalog"}) == {"catalog"}
    # agents pulls in activity, which pulls in issues
    assert expand_wipe({"agents"}) == {"agents", "activity", "issues"}
    assert expand_wipe({"providers"}) == {"providers", "activity", "issues"}
    assert expand_wipe({"activity"}) == {"activity", "issues"}
    # unknown categories dropped
    assert expand_wipe({"bogus"}) == set()


def _org(name):
    return Organization(id=str(uuid.uuid4()), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}", owner_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_reassign_keeps_everything(db):
    src_org, dst_org = _org("src"), _org("dst")
    db.add_all([src_org, dst_org])
    await db.flush()
    db.add_all([
        Persona(id=str(uuid.uuid4()), org_id=src_org.id, key="p1", name="P1"),
        Agent(id=str(uuid.uuid4()), org_id=src_org.id, name="A1"),
    ])
    await db.flush()

    await teardown_org(db, src_org.id, wipe=set(), target_org_id=dst_org.id)
    await db.flush()

    # Both moved to dst, none left in src.
    assert (await db.execute(text("SELECT count(*) FROM personas WHERE org_id=:o"), {"o": dst_org.id})).scalar() == 1
    assert (await db.execute(text("SELECT count(*) FROM agents WHERE org_id=:o"), {"o": dst_org.id})).scalar() == 1
    assert (await db.execute(text("SELECT count(*) FROM personas WHERE org_id=:o"), {"o": src_org.id})).scalar() == 0
    assert (await db.execute(text("SELECT count(*) FROM agents WHERE org_id=:o"), {"o": src_org.id})).scalar() == 0


@pytest.mark.asyncio
async def test_wipe_catalog_reassign_rest(db):
    src_org, dst_org = _org("src2"), _org("dst2")
    db.add_all([src_org, dst_org])
    await db.flush()
    db.add_all([
        Persona(id=str(uuid.uuid4()), org_id=src_org.id, key="p1", name="P1"),
        Agent(id=str(uuid.uuid4()), org_id=src_org.id, name="A1"),
    ])
    await db.flush()

    await teardown_org(db, src_org.id, wipe={"catalog"}, target_org_id=dst_org.id)
    await db.flush()

    # Catalog wiped everywhere; agent reassigned to dst.
    assert (await db.execute(text("SELECT count(*) FROM personas"))).scalar() == 0
    assert (await db.execute(text("SELECT count(*) FROM agents WHERE org_id=:o"), {"o": dst_org.id})).scalar() == 1


@pytest.mark.asyncio
async def test_wipe_agents_deletes_agents(db):
    src_org, dst_org = _org("src3"), _org("dst3")
    db.add_all([src_org, dst_org])
    await db.flush()
    db.add_all([
        Agent(id=str(uuid.uuid4()), org_id=src_org.id, name="A1"),
        Persona(id=str(uuid.uuid4()), org_id=src_org.id, key="p1", name="P1"),
    ])
    await db.flush()

    await teardown_org(db, src_org.id, wipe={"agents"}, target_org_id=dst_org.id)
    await db.flush()

    assert (await db.execute(text("SELECT count(*) FROM agents"))).scalar() == 0
    # Persona (catalog) was kept → reassigned.
    assert (await db.execute(text("SELECT count(*) FROM personas WHERE org_id=:o"), {"o": dst_org.id})).scalar() == 1
