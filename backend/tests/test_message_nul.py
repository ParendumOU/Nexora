"""NUL scrubbing on message write.

A message whose JSON metadata (or content) carries a NUL crashes Postgres text/json
extraction — one poison row broke the whole batched chat-list token aggregation, so the
sidebar failed to load platform-wide. A before_insert/update listener strips NUL on write;
the chat-list query is also made NUL-safe to heal any row that predates the listener.
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.models.chat import _strip_nul


def test_strip_nul_helper():
    assert _strip_nul("a\x00b") == "ab"
    assert _strip_nul("clean") == "clean"
    assert _strip_nul({"k": "x\x00y"}) == {"k": "xy"}
    assert _strip_nul(["a\x00", {"n": "b\x00c"}]) == ["a", {"n": "bc"}]
    assert _strip_nul(5) == 5
    assert _strip_nul(None) is None


@pytest.mark.asyncio
async def test_message_nul_stripped_on_insert(engine):
    from src.models.chat import Chat, Message

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(Chat(id="c1", user_id="u1", title="t"))
        s.add(Message(
            id="m1", chat_id="c1", role="assistant",
            content="hello\x00world",
            metadata_={"usage": {"input_tokens": "5\x00"}, "note": "a\x00b"},
        ))
        await s.commit()

    async with factory() as s:
        m = await s.get(Message, "m1")
        assert m.content == "helloworld"
        assert "\x00" not in m.metadata_["note"]
        assert m.metadata_["usage"]["input_tokens"] == "5"
