"""Unit tests for the full-platform backup / restore engine.

Runs on in-memory SQLite (FK enforcement off by default there, which mirrors the
``session_replication_role=replica`` bypass used on Postgres during restore).
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database import Base
import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.provider import Provider
from src.models.knowledge_base import KnowledgeBase, KnowledgeFile, KnowledgeChunk
from src.services import platform_backup as pb

pytestmark = pytest.mark.asyncio

ORG_A = "org-aaaa"
ORG_B = "org-bbbb"


async def _read_zip_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


async def _fresh_db():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, factory


@pytest_asyncio.fixture
async def source_db():
    """An isolated source DB per test (conftest's `db` shares one engine session-wide)."""
    eng, factory = await _fresh_db()
    async with factory() as session:
        yield session
    await eng.dispose()


@pytest_asyncio.fixture
async def target_db():
    """A second, empty in-memory DB to restore into."""
    eng, factory = await _fresh_db()
    async with factory() as session:
        yield session
    await eng.dispose()


async def _seed_source(db: AsyncSession):
    # Two orgs' worth of agents + providers (provider carries an encrypted secret).
    db.add(Agent(id="agent-a", org_id=ORG_A, name="Agent A"))
    db.add(Agent(id="agent-b", org_id=ORG_B, name="Agent B"))
    db.add(Provider(id="prov-a", org_id=ORG_A, name="P-A", provider_type="openai",
                    credentials="gAAAA-encrypted-ciphertext"))
    db.add(Provider(id="prov-b", org_id=ORG_B, name="P-B", provider_type="openai"))
    # A knowledge chunk with a real embedding vector (org A).
    db.add(KnowledgeBase(id="kb-a", org_id=ORG_A, name="KB A"))
    db.add(KnowledgeFile(id="kf-a", kb_id="kb-a", org_id=ORG_A, filename="doc.txt", status="ready", chunk_count=1))
    db.add(KnowledgeChunk(id="kc-a", file_id="kf-a", kb_id="kb-a", org_id=ORG_A,
                          chunk_index=0, content="hello world", embedding=[0.1, 0.2, 0.3]))
    await db.commit()


# ── fingerprint ──────────────────────────────────────────────────────────────────

async def test_fingerprint_is_deterministic_and_short():
    fp1 = pb.encryption_fingerprint()
    fp2 = pb.encryption_fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 16


# ── round-trip, instance scope ─────────────────────────────────────────────────────

async def test_instance_roundtrip_preserves_rows_and_secrets(source_db, target_db, tmp_path):
    await _seed_source(source_db)
    path = await pb.build_backup(source_db, scope="instance", include_vectors=True, out_dir=str(tmp_path))

    # manifest sanity
    import zipfile
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == pb.BACKUP_FORMAT
        assert manifest["scope"] == "instance"
        assert manifest["counts"]["agents"] == 2
        assert manifest["counts"]["providers"] == 2

    summary = await pb.restore_backup(target_db, await _read_zip_bytes_async(path))
    assert summary["tables"]["agents"] == 2

    agents = (await target_db.execute(select(Agent).order_by(Agent.id))).scalars().all()
    assert {a.id for a in agents} == {"agent-a", "agent-b"}

    # Encrypted secret survives verbatim.
    prov = await target_db.get(Provider, "prov-a")
    assert prov.credentials == "gAAAA-encrypted-ciphertext"

    # Vector preserved when include_vectors=True.
    chunk = await target_db.get(KnowledgeChunk, "kc-a")
    assert chunk.embedding == [0.1, 0.2, 0.3]


async def test_vectors_dropped_when_excluded(source_db, target_db, tmp_path):
    await _seed_source(source_db)
    path = await pb.build_backup(source_db, scope="instance", include_vectors=False, out_dir=str(tmp_path))
    import zipfile
    with zipfile.ZipFile(path) as zf:
        chunks = json.loads(zf.read("data/knowledge_chunks.json"))
    assert chunks[0]["embedding"] is None

    # reembed=False so the null vector stays null (no provider in test).
    await pb.restore_backup(target_db, await _read_zip_bytes_async(path), reembed=False)
    chunk = await target_db.get(KnowledgeChunk, "kc-a")
    assert chunk.embedding is None


# ── org scope ──────────────────────────────────────────────────────────────────────

async def test_org_scope_excludes_other_orgs(source_db, target_db, tmp_path):
    await _seed_source(source_db)
    path = await pb.build_backup(source_db, scope="org", org_ids=[ORG_A], include_vectors=True, out_dir=str(tmp_path))
    import zipfile
    with zipfile.ZipFile(path) as zf:
        agents = json.loads(zf.read("data/agents.json"))
        providers = json.loads(zf.read("data/providers.json"))
    assert {a["id"] for a in agents} == {"agent-a"}
    assert {p["id"] for p in providers} == {"prov-a"}


# ── fingerprint guard ───────────────────────────────────────────────────────────────

async def test_import_rejects_key_mismatch(source_db, target_db, tmp_path):
    await _seed_source(source_db)
    path = await pb.build_backup(source_db, scope="instance", out_dir=str(tmp_path))
    raw = await _read_zip_bytes_async(path)

    # Tamper the manifest fingerprint.
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "manifest.json":
                m = json.loads(data)
                m["encryption_fingerprint"] = "deadbeefdeadbeef"
                data = json.dumps(m).encode()
            zout.writestr(item, data)

    with pytest.raises(PermissionError):
        await pb.restore_backup(target_db, buf.getvalue())


# ── idempotency ─────────────────────────────────────────────────────────────────────

async def test_reimport_skip_mode_no_duplicates(source_db, target_db, tmp_path):
    await _seed_source(source_db)
    path = await pb.build_backup(source_db, scope="instance", include_vectors=True, out_dir=str(tmp_path))
    raw = await _read_zip_bytes_async(path)
    await pb.restore_backup(target_db, raw)
    summary2 = await pb.restore_backup(target_db, raw, mode="skip")
    assert summary2["tables"]["agents"] == 0  # all already present
    agents = (await target_db.execute(select(Agent))).scalars().all()
    assert len(agents) == 2


# helper: restore_backup signature uses (db, zip_bytes); tests pass session via kw shim
async def _read_zip_bytes_async(path):
    return await _read_zip_bytes(path)
