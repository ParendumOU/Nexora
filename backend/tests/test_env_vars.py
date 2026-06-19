"""Unit tests for org/user environment-variable resolution + the context overlay.

Covers the resolution precedence (org > user), name-based disambiguation when a
key has several values, Fernet round-trip, and the task-local os.environ overlay
used to inject credentials into in-process tool executors.
"""
import os
import uuid

import pytest

from src.core.security import encrypt
from src.models.env_var import EnvVar
from src.models.user import User
from src.models.org import Organization, OrgMember, OrgRole
from src.services import env_vars as ev
from src.services import env_context


async def _seed_user_org(db):
    u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex}@x.com",
             hashed_password="x", full_name="T")
    db.add(u)
    o = Organization(id=str(uuid.uuid4()), name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}",
                     owner_id=u.id)
    db.add(o)
    db.add(OrgMember(id=str(uuid.uuid4()), org_id=o.id, user_id=u.id, role=OrgRole.owner))
    await db.flush()
    return u, o


def _add(db, *, key, name, value, org_id=None, user_id=None):
    db.add(EnvVar(id=str(uuid.uuid4()), scope="org" if org_id else "user",
                  org_id=org_id, user_id=user_id, key=key, name=name,
                  value_enc=encrypt(value)))


@pytest.mark.asyncio
async def test_resolve_user_only(db):
    u, _ = await _seed_user_org(db)
    _add(db, key="STRIPE_SECRET_KEY", name="default", value="sk_user", user_id=u.id)
    await db.flush()
    out = await ev.resolve(db, ["STRIPE_SECRET_KEY"], user_id=u.id)
    assert out == {"STRIPE_SECRET_KEY": "sk_user"}


@pytest.mark.asyncio
async def test_org_shadows_user(db):
    u, o = await _seed_user_org(db)
    _add(db, key="STRIPE_SECRET_KEY", name="personal", value="sk_user", user_id=u.id)
    _add(db, key="STRIPE_SECRET_KEY", name="shared", value="sk_org", org_id=o.id)
    await db.flush()
    out = await ev.resolve(db, ["STRIPE_SECRET_KEY"], org_id=o.id, user_id=u.id)
    assert out["STRIPE_SECRET_KEY"] == "sk_org"  # org wins


@pytest.mark.asyncio
async def test_name_selection_disambiguates_duplicate_keys(db):
    u, o = await _seed_user_org(db)
    _add(db, key="STRIPE_SECRET_KEY", name="prod", value="sk_prod", org_id=o.id)
    _add(db, key="STRIPE_SECRET_KEY", name="test", value="sk_test", org_id=o.id)
    await db.flush()
    # explicit selection by name picks the right one
    out = await ev.resolve(db, ["STRIPE_SECRET_KEY"], org_id=o.id,
                           selections={"STRIPE_SECRET_KEY": "test"})
    assert out["STRIPE_SECRET_KEY"] == "sk_test"
    # without a selection: deterministic (first by name → "prod")
    out2 = await ev.resolve(db, ["STRIPE_SECRET_KEY"], org_id=o.id)
    assert out2["STRIPE_SECRET_KEY"] == "sk_prod"


@pytest.mark.asyncio
async def test_unconfigured_key_absent(db):
    u, _ = await _seed_user_org(db)
    out = await ev.resolve(db, ["MISSING_KEY"], user_id=u.id)
    assert out == {}


@pytest.mark.asyncio
async def test_resolve_requires_a_scope(db):
    out = await ev.resolve(db, ["X"])  # no org_id and no user_id
    assert out == {}


def test_tool_env_keys_reads_manifest(tmp_path, monkeypatch):
    d = tmp_path / "tools" / "builtin" / "demo_tool"
    d.mkdir(parents=True)
    (d / "tool.json").write_text('{"key":"demo_tool","env_vars":["FOO","BAR"]}')
    monkeypatch.setattr(ev, "_TOOL_ROOTS", [tmp_path / "tools" / "builtin"])
    ev.reload_env_keys()
    assert ev.tool_env_keys("demo_tool") == ["FOO", "BAR"]
    assert ev.tool_env_keys("nope") == []
    ev.reload_env_keys()


def test_env_context_overlay_applies_and_resets():
    os.environ.pop("ENVCTX_X", None)
    assert os.getenv("ENVCTX_X") is None
    with env_context.use_env({"ENVCTX_X": "v"}):
        assert os.getenv("ENVCTX_X") == "v"
    assert os.getenv("ENVCTX_X") is None  # reset after the block


def test_env_context_empty_overlay_is_noop():
    with env_context.use_env(None):
        pass  # must not raise / must not install anything harmful
    with env_context.use_env({}):
        pass


@pytest.mark.asyncio
async def test_env_context_isolated_across_tasks():
    import asyncio
    os.environ.pop("ENVCTX_ISO", None)

    async def worker(val):
        with env_context.use_env({"ENVCTX_ISO": val}):
            await asyncio.sleep(0.01)
            return os.getenv("ENVCTX_ISO")

    results = await asyncio.gather(worker("A"), worker("B"))
    assert results == ["A", "B"]
    assert os.getenv("ENVCTX_ISO") is None
