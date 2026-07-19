"""Capability-based provider selection (providers/capabilities.py).

Auxiliary pipelines (embeddings, stt, vision) must pick providers from the
seed-declared `capabilities` block, never from hardcoded type lists.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401
from src.models.provider import Provider
from src.providers import capabilities as caps


@pytest_asyncio.fixture
async def session_factory(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(caps, "AsyncSessionLocal", factory)
    yield factory
    await eng.dispose()


def test_get_capability_reads_seed_block():
    # openai seed declares all three capabilities.
    emb = caps.get_capability("openai", "embeddings")
    assert emb and emb["model"] == "text-embedding-3-small" and emb["dimensions"] == 1536
    stt = caps.get_capability("groq", "stt")
    assert stt and stt["model"] == "whisper-large-v3"
    vision = caps.get_capability("gemini-api", "vision")
    assert vision and vision["api"] == "openai_compat"
    # `api` defaults to the seed's stream_type when not explicit.
    assert caps.get_capability("groq", "stt")["api"] == "openai_compat"


def test_get_capability_absent_for_undeclared():
    assert caps.get_capability("groq", "embeddings") is None
    assert caps.get_capability("groq", "vision") is None
    assert caps.get_capability("nonexistent-type", "stt") is None


@pytest.mark.asyncio
async def test_find_capability_providers_filters_and_orders(session_factory):
    org = str(uuid.uuid4())
    async with session_factory() as db:
        db.add(Provider(id=str(uuid.uuid4()), org_id=org, name="groq-lo",
                        provider_type="groq", is_active=True, priority=1))
        db.add(Provider(id=str(uuid.uuid4()), org_id=org, name="openai-hi",
                        provider_type="openai", is_active=True, priority=9))
        db.add(Provider(id=str(uuid.uuid4()), org_id=org, name="openai-off",
                        provider_type="openai", is_active=False, priority=99))
        db.add(Provider(id=str(uuid.uuid4()), org_id=org, name="cerebras",
                        provider_type="cerebras", is_active=True, priority=5))
        await db.commit()

    stt = await caps.find_capability_providers(org, "stt")
    assert [p.name for p, _ in stt] == ["openai-hi", "groq-lo"]
    assert stt[0][1]["model"] == "whisper-1"
    assert stt[1][1]["model"] == "whisper-large-v3"

    emb = await caps.find_capability_providers(org, "embeddings")
    assert [p.name for p, _ in emb] == ["openai-hi"]  # groq/cerebras undeclared, inactive skipped

    # Unknown org → empty, never raises.
    assert await caps.find_capability_providers(str(uuid.uuid4()), "stt") == []
