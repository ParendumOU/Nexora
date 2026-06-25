"""
Test configuration and shared fixtures.

Uses an in-memory SQLite database via aiosqlite so that no running Postgres or
Redis instance is required.  The FastAPI app is created without the production
lifespan (which would attempt to connect to both) and the rate-limiter is
patched to a no-op so that auth endpoints do not need a live Redis.
"""
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

# Force development environment so the production secret-key validator is skipped
# and docs URLs are enabled.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")
# A valid Fernet key = 32 url-safe-base64 bytes. urlsafe_b64encode(b"0"*32).
os.environ.setdefault("ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
# NOTE: src.core.database builds a module-level async engine at import time from
# DATABASE_URL (default Postgres+asyncpg). The engine is created lazily — no
# connection is opened until a query runs — so importing src.* needs asyncpg
# installed (it is a core dependency, present in CI and the dev extra) but does
# NOT require a running Postgres. The no-DB unit suite never touches this engine:
# every fixture below builds its own in-memory SQLite engine. Integration tests
# (marked `integration`) rely on a real Postgres via DATABASE_URL in CI.

from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Import Base and all models so that create_all picks up every table.
from src.core.database import Base, get_db
import src.models  # noqa: F401 — registers all ORM models with Base.metadata

# Some models use Postgres JSONB columns (e.g. agent_versions.snapshot). The
# unit suite runs on in-memory SQLite, whose compiler can't render JSONB, so
# create_all() would raise CompileError. Map JSONB → JSON on the sqlite dialect.
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB
from sqlalchemy.ext.compiler import compiles as _compiles


@_compiles(_PG_JSONB, "sqlite")
def _render_jsonb_as_json_on_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


# ---------------------------------------------------------------------------
# Build a test-only FastAPI app (no lifespan, same routers as production).
# ---------------------------------------------------------------------------

def _build_test_app() -> FastAPI:
    from src.api.routers import (
        auth, users, providers, agents, projects, chats, tasks, logs,
        skills, mcp_servers, tools, personas, git_credentials, git_proxy,
        orgs, seeds, issues, integrations, usage, model_profiles,
        provider_types, memories, teams,
        schedules as schedules_router,
        board as board_router,
        knowledge_bases as knowledge_bases_router,
        user_api_keys, notifications, user_backup,
        webhook_rules as webhook_rules_router,
        custom_webhook as custom_webhook_router,
        agent_messages as agent_messages_router,
        proposals as proposals_router,
        plans as plans_router,
        totp as totp_router,
        search as search_router,
        marketplace as marketplace_router,
        system as system_router,
        cli_hooks as cli_hooks_router,
        goals as goals_router,
        approvals as approvals_router,
        outcomes as outcomes_router,
        org_roles as org_roles_router,
    )

    app = FastAPI(title="Nexora Test")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = "/api"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(totp_router.router, prefix=prefix)
    app.include_router(search_router.router, prefix=prefix)
    app.include_router(marketplace_router.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(user_api_keys.router, prefix=prefix)
    app.include_router(user_backup.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(providers.router, prefix=prefix)
    app.include_router(agents.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(chats.router, prefix=prefix)
    app.include_router(tasks.router, prefix=prefix)
    app.include_router(logs.router, prefix=prefix)
    app.include_router(skills.router, prefix=prefix)
    app.include_router(mcp_servers.router, prefix=prefix)
    app.include_router(tools.router, prefix=prefix)
    app.include_router(personas.router, prefix=prefix)
    app.include_router(git_credentials.router, prefix=prefix)
    app.include_router(git_proxy.router, prefix=prefix)
    app.include_router(orgs.router, prefix=prefix)
    app.include_router(seeds.router, prefix=prefix)
    app.include_router(issues.router, prefix=prefix)
    app.include_router(integrations.router, prefix=prefix)
    app.include_router(usage.router, prefix=prefix)
    app.include_router(model_profiles.router, prefix=prefix)
    app.include_router(provider_types.router, prefix=prefix)
    app.include_router(memories.router)
    app.include_router(teams.router, prefix=prefix)
    app.include_router(schedules_router.router, prefix=prefix)
    app.include_router(board_router.router, prefix=prefix)
    app.include_router(webhook_rules_router.router, prefix=prefix)
    app.include_router(custom_webhook_router.router, prefix=prefix)
    app.include_router(agent_messages_router.router, prefix=prefix)
    app.include_router(proposals_router.router, prefix=prefix)
    app.include_router(plans_router.router, prefix=prefix)
    app.include_router(knowledge_bases_router.router, prefix=prefix)
    app.include_router(system_router.router, prefix=prefix)
    app.include_router(cli_hooks_router.router, prefix=prefix)
    app.include_router(goals_router.router, prefix=prefix)
    app.include_router(approvals_router.router, prefix=prefix)
    app.include_router(outcomes_router.router, prefix=prefix)
    app.include_router(org_roles_router.router, prefix=prefix)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    return app


_test_app = _build_test_app()

# Routers bind `rate_limit` at import (`from src.core.rate_limit import rate_limit`),
# so patching the source module doesn't reach them. Replace the bound name in every
# already-imported router module with an async no-op so endpoint tests never touch
# Redis (which would otherwise raise ConnectionError / "event loop is closed").
import sys as _sys
for _modname, _mod in list(_sys.modules.items()):
    if _modname.startswith("src.api.routers") and hasattr(_mod, "rate_limit"):
        _mod.rate_limit = AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# Database fixtures — in-memory SQLite
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            # The in-memory engine is session-scoped (one shared SQLite DB), so
            # rows a test flushes/commits would otherwise leak into later tests
            # (e.g. agents reassigned to a target org surviving into a global
            # count assertion). Clear every table after each test for isolation.
            await session.rollback()
            # Unordered delete (SQLite enforces no FKs by default, and the schema
            # has a mutually-dependent organizations<->users cycle that makes
            # sorted_tables warn). Clear everything for per-test isolation.
            for table in Base.metadata.tables.values():
                await session.execute(table.delete())
            await session.commit()


# ---------------------------------------------------------------------------
# HTTP client fixture — overrides get_db and no-ops the rate limiter
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(db):
    async def _override_db():
        yield db

    _test_app.dependency_overrides[get_db] = _override_db

    # Patch rate_limit to a no-op so auth endpoints don't need Redis.
    with patch("src.core.rate_limit.rate_limit", new=AsyncMock(return_value=None)):
        async with AsyncClient(
            transport=ASGITransport(app=_test_app),
            base_url="http://test",
        ) as c:
            yield c

    _test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# auth_headers fixture — registers a user and returns Bearer headers
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_headers(client):
    """Register a user, log in, and return Authorization headers."""
    await client.post("/api/auth/register", json={
        "email": "fixture@example.com",
        "password": "FixturePass1",
        "full_name": "Fixture User",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "fixture@example.com",
        "password": "FixturePass1",
    })
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"Login did not return a token: {data}"
    return {"Authorization": f"Bearer {token}"}
