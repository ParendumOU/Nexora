"""OpenAI-compatible reasoning_content is surfaced as a <think> block (GitLab #214 / thinking)."""
from types import SimpleNamespace

import pytest

import src.providers.router as router
from src.providers.cli_streams import _METADATA_PREFIX


class _Delta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.reasoning = None
        self.tool_calls = None


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


async def _fake_stream():
    yield _Chunk([_Choice(_Delta(reasoning_content="Let me think"))])
    yield _Chunk([_Choice(_Delta(reasoning_content=" carefully"))])
    yield _Chunk([_Choice(_Delta(content="The answer"), finish_reason="stop")])


class _Completions:
    async def create(self, **kw):
        return _fake_stream()


class _FakeClient:
    def __init__(self, **kw):
        pass
    chat = SimpleNamespace(completions=_Completions())


async def _collect(gen):
    out = []
    async for c in gen:
        if not c.startswith(_METADATA_PREFIX):
            out.append(c)
    return "".join(out)


async def test_reasoning_content_wrapped_in_think(monkeypatch):
    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    provider = SimpleNamespace(
        provider_type="openai", base_url="http://fake", model_name="m",
        credentials=None, auth_type="apikey", id="p1", name="P",
    )
    text = await _collect(router.stream_openai_compat(provider, [{"role": "user", "content": "hi"}]))

    # reasoning surfaced as a single <think> block, closed before the answer
    assert "<think>Let me think carefully</think>" in text
    assert text.strip().endswith("The answer")
    # the closing tag precedes the answer (reasoning is not mixed into the body)
    assert text.index("</think>") < text.index("The answer")
