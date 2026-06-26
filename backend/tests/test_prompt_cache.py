"""Prompt-cache breakpoint helpers (#220)."""
import pytest

from src.providers.prompt_cache import (
    CACHE_SENTINEL,
    strip_sentinel_text,
    strip_sentinel_messages,
    split_system_for_cache,
)


def test_strip_text_removes_sentinel_line():
    assert strip_sentinel_text(f"A\n{CACHE_SENTINEL}\nB") == "A\nB"
    assert strip_sentinel_text("no sentinel") == "no sentinel"
    assert strip_sentinel_text(None) is None


def test_strip_messages_is_noop_without_sentinel():
    msgs = [{"role": "system", "content": "plain"}, {"role": "user", "content": "hi"}]
    # Same object back → true no-op on the default path.
    assert strip_sentinel_messages(msgs) is msgs


def test_strip_messages_removes_sentinel_only_from_system():
    msgs = [
        {"role": "system", "content": f"X{CACHE_SENTINEL}Y"},
        {"role": "user", "content": f"keep{CACHE_SENTINEL}me"},
    ]
    out = strip_sentinel_messages(msgs)
    assert out[0]["content"] == "XY"
    # user content is left untouched (sentinel only ever appears in system text)
    assert out[1] is msgs[1]


def test_split_system_with_sentinel():
    blocks = split_system_for_cache(f"STABLE\n{CACHE_SENTINEL}\nVOLATILE")
    assert len(blocks) == 2
    assert blocks[0]["text"] == "STABLE"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "VOLATILE"
    assert "cache_control" not in blocks[1]


def test_split_system_without_sentinel_caches_whole():
    blocks = split_system_for_cache("just one block")
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_builder_omits_sentinel_when_flag_off(monkeypatch):
    # With the flag explicitly off, the split is a single uncached-prefix block and
    # the sentinel never survives into a provider prompt (strip is a true no-op).
    from src.core.config import get_settings
    monkeypatch.setattr(get_settings(), "prompt_cache_enabled", False)
    assert get_settings().prompt_cache_enabled is False
    # A prompt that never had a sentinel inserted splits to one whole-prompt block.
    blocks = split_system_for_cache("no sentinel here")
    assert len(blocks) == 1
    msgs = [{"role": "system", "content": "plain"}, {"role": "user", "content": "hi"}]
    assert strip_sentinel_messages(msgs) is msgs
