"""Unit tests for marketplace import helpers — the agent sub-dependency install
logic. Covers the pure URL-derivation + auth-header helpers and the
`_install_dependency_package` branch logic against an in-memory SQLite session.
"""
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401 — register all ORM models
from src.models.skill import Skill
from src.models.tool import Tool
from src.models.persona import Persona
from src.models.agent import Agent
from src.api.routers import seeds as seeds_router
from src.api.routers.seeds import write_custom_seed
from src.api.routers.marketplace import (
    _dep_url_for,
    _marketplace_headers,
    _install_dependency_package,
    _create_agent_row,
    _origin_of,
)


# ── Redirect custom-seed writes to a tmp dir ────────────────────────────────
# `write_custom_seed` (now used by the import path) writes into the repo's
# gitignored custom seed dirs. Redirect those to a per-test tmp dir so tests
# never pollute the working tree or shadow real seeds.
@pytest.fixture(autouse=True)
def _tmp_seed_roots(tmp_path, monkeypatch):
    roots = {
        "skill": tmp_path / "skills" / "custom",
        "tool": tmp_path / "tools" / "custom",
        "persona": tmp_path / "personas" / "custom",
        "agent": tmp_path / "agents" / "custom",
    }
    monkeypatch.setattr(seeds_router, "_CUSTOM_ROOTS", roots)
    return roots


# ── _dep_url_for ────────────────────────────────────────────────────────────


def test_dep_url_replaces_trailing_segment():
    url = "https://mk.test/api/packages/parent-agent"
    assert _dep_url_for(url, "child-skill") == "https://mk.test/api/packages/child-skill"


def test_dep_url_strips_trailing_slash():
    url = "https://mk.test/api/packages/parent/"
    assert _dep_url_for(url, "child") == "https://mk.test/api/packages/child"


def test_dep_url_preserves_origin_and_prefix():
    url = "http://localhost:8812/api/packages/foo"
    assert _dep_url_for(url, "bar") == "http://localhost:8812/api/packages/bar"


def test_dep_url_single_token_fallback():
    # No slash to partition on → returns original url unchanged.
    assert _dep_url_for("packages", "bar") == "packages"


# ── _marketplace_headers ────────────────────────────────────────────────────


def test_marketplace_headers_empty_when_no_key():
    user = SimpleNamespace(marketplace_api_key_enc=None)
    assert _marketplace_headers(user) == {}


def test_marketplace_headers_sets_bearer_from_decrypted_key(monkeypatch):
    monkeypatch.setattr(
        "src.api.routers.marketplace.decrypt" if False else "src.core.security.decrypt",
        lambda _enc: "nmk_secret123",
    )
    user = SimpleNamespace(marketplace_api_key_enc="encrypted-blob")
    headers = _marketplace_headers(user)
    assert headers["Authorization"] == "Bearer nmk_secret123"


def test_marketplace_headers_swallows_decrypt_errors(monkeypatch):
    def boom(_enc):
        raise ValueError("bad key")

    monkeypatch.setattr("src.core.security.decrypt", boom)
    user = SimpleNamespace(marketplace_api_key_enc="encrypted-blob")
    # Must not raise; returns no auth header.
    assert _marketplace_headers(user) == {}


# ── _install_dependency_package (against in-memory SQLite) ──────────────────


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await eng.dispose()


ORG = str(uuid.uuid4())


@pytest.mark.asyncio
async def test_install_skill_dependency(db):
    reason = await _install_dependency_package(
        "skill", {"slug": "web_search", "name": "Web Search", "description": "d"}, ORG, db
    )
    await db.commit()
    assert reason is None
    rows = (await db.execute(select(Skill).where(Skill.org_id == ORG))).scalars().all()
    assert len(rows) == 1
    assert rows[0].key == "web_search"
    assert rows[0].is_builtin is False


@pytest.mark.asyncio
async def test_install_skill_dependency_idempotent(db):
    db.add(Skill(id=str(uuid.uuid4()), org_id=ORG, key="dupe", name="Dupe", is_builtin=False))
    await db.commit()
    reason = await _install_dependency_package("skill", {"slug": "dupe"}, ORG, db)
    assert reason == "already installed"


@pytest.mark.asyncio
async def test_install_tool_dependency(db):
    reason = await _install_dependency_package(
        "tool", {"key": "slack", "name": "Slack"}, ORG, db
    )
    await db.commit()
    assert reason is None
    rows = (await db.execute(select(Tool).where(Tool.org_id == ORG))).scalars().all()
    assert len(rows) == 1
    assert rows[0].key == "slack"


@pytest.mark.asyncio
async def test_install_persona_dependency_normalizes_key(db):
    reason = await _install_dependency_package(
        "persona",
        {"slug": "QA Engineer", "name": "QA Engineer", "manifest": {"soul": {"tone": "x"}}},
        ORG,
        db,
    )
    await db.commit()
    assert reason is None
    rows = (await db.execute(select(Persona).where(Persona.org_id == ORG))).scalars().all()
    assert len(rows) == 1
    # spaces lowercased + underscored
    assert rows[0].key == "qa_engineer"
    assert rows[0].soul == {"tone": "x"}


@pytest.mark.asyncio
async def test_install_unsupported_type_returns_reason(db):
    reason = await _install_dependency_package("widget", {"slug": "x"}, ORG, db)
    assert reason is not None
    assert "unsupported" in reason.lower()


@pytest.mark.asyncio
async def test_install_agent_dependency_not_supported_leaf(db):
    # Agent deps are not auto-installed by the dependency installer (only leaf types).
    reason = await _install_dependency_package("agent", {"slug": "some-agent"}, ORG, db)
    assert reason is not None
    assert "unsupported" in reason.lower()


# ── write_custom_seed (file materialization) ────────────────────────────────


def test_write_custom_seed_writes_files_and_manifest(_tmp_seed_roots):
    dest = write_custom_seed(
        "skill", "my_skill",
        {"SKILL.md": "# doc", "executor.py": "print('hi')"},
        {"key": "my_skill", "name": "My Skill"},
    )
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# doc"
    assert (dest / "executor.py").exists()
    # manifest written because no skill.json was in files
    assert (dest / "skill.json").exists()


def test_write_custom_seed_zip_slip_guard(_tmp_seed_roots):
    dest = write_custom_seed("tool", "t", {"../escape.py": "evil"}, {})
    # The traversal file must NOT be written outside the dest dir.
    assert not (dest.parent / "escape.py").exists()


def test_write_custom_seed_rejects_bad_type():
    with pytest.raises(ValueError):
        write_custom_seed("widget", "x", {}, {})


# ── leaf dep installs now materialize files on disk ─────────────────────────


@pytest.mark.asyncio
async def test_skill_dep_writes_seed_files(db, _tmp_seed_roots):
    await _install_dependency_package(
        "skill",
        {"slug": "cool_skill", "name": "Cool", "files": {"SKILL.md": "x"},
         "manifest": {"key": "cool_skill"}},
        ORG, db,
    )
    await db.commit()
    seed_dir = _tmp_seed_roots["skill"] / "cool_skill"
    assert (seed_dir / "SKILL.md").exists()
    assert (seed_dir / "skill.json").exists()


# ── _create_agent_row (the persona/agent import blocker fix) ────────────────


@pytest.mark.asyncio
async def test_create_agent_row_writes_seed_and_db(db, _tmp_seed_roots):
    data = {
        "slug": "My SRE", "name": "My SRE",
        "manifest": {
            "name": "My SRE", "system_prompt": "be calm",
            "tools": ["pagerduty", "kubernetes"], "soul": {"tone": "steady"},
            "temperature": 0.1,
        },
        "files": {"AGENT.md": "# On-call"},
    }
    reason = await _create_agent_row(data, ORG, db)
    await db.commit()
    assert reason is None
    rows = (await db.execute(select(Agent).where(Agent.org_id == ORG))).scalars().all()
    assert len(rows) == 1
    a = rows[0]
    assert a.name == "My SRE"
    assert a.tools == ["pagerduty", "kubernetes"]
    assert a.system_prompt == "be calm"
    assert a.is_builtin is False
    # seed files materialized under the canonical key (slug → my_sre)
    seed_dir = _tmp_seed_roots["agent"] / "my_sre"
    assert (seed_dir / "AGENT.md").exists()
    assert (seed_dir / "agent.json").exists()


@pytest.mark.asyncio
async def test_create_agent_row_idempotent(db, _tmp_seed_roots):
    data = {"slug": "Dup Agent", "name": "Dup Agent", "manifest": {"name": "Dup Agent"}}
    assert await _create_agent_row(data, ORG, db) is None
    await db.commit()
    assert await _create_agent_row(data, ORG, db) == "already installed"


# ── _origin_of (pack constituent URL derivation) ────────────────────────────


def test_origin_of_starter_pack_url():
    assert _origin_of("https://mk.test/api/starter-packs/sre-pack") == "https://mk.test"


def test_origin_of_packages_url():
    assert _origin_of("http://localhost:8812/api/packages/foo") == "http://localhost:8812"
