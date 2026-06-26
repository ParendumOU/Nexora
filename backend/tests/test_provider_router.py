"""stream_response no-attempt diagnostics — a chat that resolves to zero usable providers
must explain WHY instead of the opaque "No available providers".
"""
from types import SimpleNamespace
import pytest

from src.providers.router import stream_response
from src.providers.exceptions import AllProvidersExhausted


async def _drain(providers):
    async for _ in stream_response(providers, [{"role": "user", "content": "hi"}]):
        pass


@pytest.mark.asyncio
async def test_no_providers_configured_message():
    with pytest.raises(AllProvidersExhausted) as exc:
        await _drain([])
    assert "No AI provider is set" in str(exc.value)


@pytest.mark.asyncio
async def test_all_inactive_message():
    inactive = SimpleNamespace(
        id="p1", name="OpenAI API", provider_type="openai", is_active=False,
        cooling_until=None, model_name="gpt-4o-mini",
    )
    with pytest.raises(AllProvidersExhausted) as exc:
        await _drain([(inactive, None)])
    assert "inactive" in str(exc.value).lower()
