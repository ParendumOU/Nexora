"""Auto-delivered file dedupe by path (#workspace files panel).

Re-writing the same file must UPDATE one ChatFile entry (broadcasting file_updated),
not pile up a new row per write. Hits the in-memory sqlite engine; pubsub is stubbed.
"""
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.core.config import get_settings
from src.models.chat_file import ChatFile
import src.services.agent_tools.tool_executor as te


@pytest.mark.asyncio
async def test_store_and_register_dedupes_by_path(engine, monkeypatch, tmp_path):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(te, "AsyncSessionLocal", factory)
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    events = []

    async def _bc(_cid, payload):
        events.append(payload.get("type"))
    monkeypatch.setattr("src.core.pubsub.broadcast", _bc)

    r1 = await te._store_and_register_file("root1", "root1", "u1", "README.md", b"v1", folder="docs")
    r2 = await te._store_and_register_file("root1", "root1", "u1", "README.md", b"v2-longer", folder="docs")

    # same logical file → same row id, second call is an update
    assert r1["file_id"] == r2["file_id"]
    assert r1.get("updated") is False and r2.get("updated") is True
    assert events[0] == "file_created" and "file_updated" in events

    async with factory() as db:
        n = (await db.execute(
            select(func.count(ChatFile.id)).where(ChatFile.root_chat_id == "root1")
        )).scalar()
        assert n == 1  # one entry, not two
        row = (await db.execute(select(ChatFile).where(ChatFile.root_chat_id == "root1"))).scalar_one()
        assert row.size_bytes == len(b"v2-longer")  # reflects the latest write
        assert row.folder == "docs" and row.original_filename == "README.md"

    # a DIFFERENT path (different folder) is a separate entry
    await te._store_and_register_file("root1", "root1", "u1", "README.md", b"x", folder="src")
    async with factory() as db:
        n = (await db.execute(
            select(func.count(ChatFile.id)).where(ChatFile.root_chat_id == "root1")
        )).scalar()
        assert n == 2

    # cleanup so other tests' global counts aren't polluted (shared session engine)
    async with factory() as db:
        await db.execute(ChatFile.__table__.delete())
        await db.commit()
