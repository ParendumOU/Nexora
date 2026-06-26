"""Provider Router — LLM fallback chain with rate-limit awareness."""
from __future__ import annotations

import copy
import json
import asyncio
import logging
from typing import AsyncIterator

from src.core.redis import get_redis
from src.core.security import decrypt
from src.models.provider import Provider
from src.providers.oauth_sessions import read_provider_credentials
from src.providers.exceptions import ProviderError, RateLimitError, AllProvidersExhausted  # noqa: F401 — re-exported
from src.providers.provider_health import (
    parse_retry_after,
    record_provider_success,
    record_provider_failure,
)
from src.providers.cli_streams import (
    _METADATA_PREFIX,  # noqa: F401 — re-exported for callers that import it from here
    _STATUS_PREFIX,  # noqa: F401 — re-exported
    _status_event,
    _stream_claude_cli,
    _stream_gemini_cli,
    _stream_codex_cli,
)

logger = logging.getLogger(__name__)

RATE_LIMIT_KEY = "provider:ratelimit:{provider_id}"


def _fire_metering(org_id: int | None) -> None:
    """Non-blocking fire-and-forget: increments LLM call counter in billing worker."""
    if not org_id:
        return
    from src.core.config import get_settings
    billing_url = get_settings().billing_worker_url
    if not billing_url:
        return
    import threading, urllib.request, json as _json
    secret = get_settings().secret_key

    def _post():
        try:
            body = _json.dumps({"org_id": org_id}).encode()
            req = urllib.request.Request(
                f"{billing_url}/api/metering/llm_call",
                data=body,
                headers={"Content-Type": "application/json", "X-Internal-Secret": secret},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass  # never block the LLM stream

    threading.Thread(target=_post, daemon=True).start()

# Populated after stream functions are defined — see _build_provider_registry() below.
_OPENAI_COMPAT_URLS: dict[str, str | None] = {}
_DEFAULT_MODELS: dict[str, str] = {}
_OPENAI_COMPAT_TYPES: set[str] = set()


def _temp(kw: dict) -> float | None:
    """Per-agent sampling temperature passed by the caller, or None to use the
    provider/SDK default. Non-numeric values are ignored (treated as unset)."""
    t = kw.get("temperature")
    return float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def _is_gemini_rate_limit(exc: object) -> bool:
    """Prefer the typed HTTP status (429) on the genai error; fall back to a string
    match so a wording change can't silently turn a limit into a hard failure."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return True
    err = str(exc).lower()
    return any(s in err for s in ("quota", "rate", "resource_exhausted", "429"))


def _is_bedrock_throttle(exc: object) -> bool:
    """Prefer the botocore error code; fall back to a string match."""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = (resp.get("Error") or {}).get("Code", "")
        if code in ("ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"):
            return True
    err = str(exc).lower()
    return "throttling" in err or "too many" in err


# ── Rate limit helpers ────────────────────────────────────────────────────────

async def is_cooling(provider_id: str) -> bool:
    redis = get_redis()
    return await redis.exists(RATE_LIMIT_KEY.format(provider_id=provider_id)) == 1


async def set_cooling(provider_id: str, seconds: int):
    redis = get_redis()
    await redis.setex(RATE_LIMIT_KEY.format(provider_id=provider_id), seconds, "1")


# ── Credential helpers ────────────────────────────────────────────────────────

def _get_credentials(provider: Provider) -> dict:
    if provider.auth_type == "oauth" and provider.auth_path:
        live = _load_oauth_creds(provider.provider_type, provider.auth_path)
        if live:
            return live
    if not provider.credentials:
        return {}
    try:
        return json.loads(decrypt(provider.credentials))
    except Exception as exc:
        logger.warning("Failed to decrypt credentials for provider %s: %s", provider.name, exc)
        return {}


def _load_oauth_creds(provider_type: str, auth_path: str) -> dict | None:
    try:
        creds = read_provider_credentials(provider_type, auth_path)
        if creds:
            return creds
    except Exception as e:
        logger.warning(f"Failed to load OAuth creds from {auth_path}: {e}")
    return None


# ── Provider stream functions ─────────────────────────────────────────────────

async def stream_claude(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    if provider.auth_type == "oauth" and provider.auth_path:
        async for chunk in _stream_claude_cli(provider, messages, **kw):
            yield chunk
        return

    import anthropic
    creds = _get_credentials(provider)
    token = creds.get("access_token") or creds.get("api_key", "")
    model = kw.get("model_override") or provider.model_name or _DEFAULT_MODELS.get("claude", "")

    def _to_anthropic_messages(msgs: list[dict]) -> list[dict]:
        result = []
        for m in msgs:
            content = m["content"]
            if not isinstance(content, list):
                result.append(m)
                continue
            blocks = []
            for block in content:
                if block.get("type") == "text":
                    blocks.append({"type": "text", "text": block["text"]})
                elif block.get("type") == "image_url":
                    url = (block.get("image_url") or {}).get("url", "")
                    if url.startswith("data:"):
                        header, _, data = url.partition(",")
                        media_type = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
                    else:
                        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
            result.append({"role": m["role"], "content": blocks})
        return result

    try:
        client = anthropic.AsyncAnthropic(api_key=token)
        if kw.get("prompt_cache"):
            # #220: layered cache. Pull system out of a role=system message (the
            # main chat / sub-agent paths pass it that way) or the kwarg, split it
            # at the cache breakpoint, and cache the stable prefix. The system
            # message is removed from the array (Anthropic wants system top-level).
            from src.providers.prompt_cache import split_system_for_cache
            _sys_parts = [m["content"] for m in messages
                          if m.get("role") == "system" and isinstance(m.get("content"), str)]
            _msgs_for_call = [m for m in messages if m.get("role") != "system"]
            system_text = kw.get("system_prompt") or ("\n\n".join(_sys_parts) if _sys_parts else None)
            system_param = split_system_for_cache(system_text) if system_text else None
        else:
            system_prompt = kw.get("system_prompt")
            system_param = (
                [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
                if system_prompt else None
            )
            _msgs_for_call = messages
        final_msg = None
        _claude_kw: dict = dict(
            model=model,
            max_tokens=kw.get("max_tokens", 8192),
            messages=_to_anthropic_messages(_msgs_for_call),
            system=system_param,
        )
        _t = _temp(kw)
        if _t is not None:
            # Anthropic accepts temperature in [0, 1]; clamp so an out-of-range
            # per-agent setting can't 400 the request.
            _claude_kw["temperature"] = min(max(_t, 0.0), 1.0)
        # Mode → extended thinking (think/deep on a reasoning-capable Claude). The
        # model reasons server-side for a better answer. Anthropic requires no custom
        # temperature with thinking, and max_tokens > budget, so adjust both.
        from src.providers.reasoning import anthropic_thinking
        _think = anthropic_thinking(kw.get("mode"), model)
        if _think:
            _claude_kw["thinking"] = _think
            _claude_kw.pop("temperature", None)
            _claude_kw["max_tokens"] = max(_claude_kw.get("max_tokens", 8192),
                                           _think["budget_tokens"] + 4096)
        # Native tool calling (#214): expose schema-backed tools; results are
        # converted back into the ```tool_calls fence below.
        _tool_keys = kw.get("tool_keys")
        if _tool_keys:
            from src.services.agent_tools.tool_schemas import build_provider_tools
            _atools = build_provider_tools(_tool_keys, "anthropic")
            if _atools:
                _claude_kw["tools"] = _atools
        async with client.messages.stream(**_claude_kw) as stream:
            async for text in stream.text_stream:
                yield text
            try:
                final_msg = await stream.get_final_message()
            except Exception:
                pass
        if final_msg is not None:
            from src.providers.native_tools import anthropic_tool_uses, fence_from_calls
            _native_calls = anthropic_tool_uses(final_msg)
            if _native_calls:
                yield fence_from_calls(_native_calls)
        from src.providers.cli_streams import _metadata_event
        meta: dict = {"provider": "claude", "model": model}
        if final_msg and final_msg.usage:
            u = final_msg.usage
            meta["usage"] = {
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
            }
            cache_read = getattr(u, "cache_read_input_tokens", None)
            cache_created = getattr(u, "cache_creation_input_tokens", None)
            if cache_read:
                meta["usage"]["cached_input_tokens"] = cache_read
            if cache_created:
                meta["usage"]["cache_creation_input_tokens"] = cache_created
        # Anthropic reports stop_reason="max_tokens" when the reply hit the cap;
        # normalize to finish_reason="length" so the router auto-continues.
        if final_msg and getattr(final_msg, "stop_reason", None) == "max_tokens":
            meta["finish_reason"] = "length"
        yield _metadata_event(meta)
    except anthropic.RateLimitError as e:
        raise RateLimitError("Claude rate limit", cooldown_seconds=parse_retry_after(e))
    except anthropic.AuthenticationError as e:
        raise ProviderError(f"Claude auth error: {e}")


async def stream_gemini(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    if provider.auth_type == "oauth" and provider.auth_path:
        async for chunk in _stream_gemini_cli(provider, messages, **kw):
            yield chunk
        return

    creds = _get_credentials(provider)
    model_name = kw.get("model_override") or provider.model_name or _DEFAULT_MODELS.get("gemini", "")

    try:
        from google import genai as genai_async
        client = genai_async.Client(api_key=creds.get("api_key", ""))
        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in messages if m["role"] != "system"
        ]
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        config: dict = {}
        if system_parts:
            config["system_instruction"] = system_parts[-1]
        if kw.get("max_tokens"):
            config["max_output_tokens"] = kw["max_tokens"]
        _t = _temp(kw)
        if _t is not None:
            config["temperature"] = _t
        # Mode → Gemini 2.5 thinking budget (0 disables for flash; a budget for
        # think/deep). Left unset for models without a thinking knob.
        from src.providers.reasoning import gemini_thinking_budget
        _tb = gemini_thinking_budget(kw.get("mode"), model_name)
        if _tb is not None:
            config["thinking_config"] = {"thinking_budget": _tb}
        # Native tool calling (#214): expose schema-backed tools; function_call parts
        # are converted back into the ```tool_calls fence below.
        _tool_keys = kw.get("tool_keys")
        if _tool_keys:
            from src.services.agent_tools.tool_schemas import build_provider_tools
            _gdecls = build_provider_tools(_tool_keys, "gemini")
            if _gdecls:
                config["tools"] = [{"function_declarations": _gdecls}]
        _gem_calls: list[dict] = []

        async for chunk in client.aio.models.generate_content_stream(
            model=model_name,
            contents=contents,
            config=config or None,
        ):
            try:
                _txt = chunk.text
            except Exception:
                _txt = None
            if _txt:
                yield _txt
            if _tool_keys:
                from src.providers.native_tools import gemini_function_calls
                _gem_calls.extend(gemini_function_calls(chunk))
        if _gem_calls:
            from src.providers.native_tools import fence_from_calls
            yield fence_from_calls(_gem_calls)
    except ImportError:
        # Fall back to legacy synchronous SDK via thread if google-genai not installed
        import google.generativeai as genai_legacy
        genai_legacy.configure(api_key=creds.get("api_key", ""))
        model = genai_legacy.GenerativeModel(model_name)
        history = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
            for m in messages if m["role"] != "system"
        ]
        try:
            resp = await asyncio.to_thread(
                model.generate_content,
                history[-1]["parts"] if history else ["Hello"],
                stream=True,
            )
            for chunk in resp:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            if _is_gemini_rate_limit(e):
                raise RateLimitError(f"Gemini rate limit: {e}", cooldown_seconds=parse_retry_after(e))
            raise ProviderError(f"Gemini error: {e}")
    except Exception as e:
        if _is_gemini_rate_limit(e):
            raise RateLimitError(f"Gemini rate limit: {e}", cooldown_seconds=parse_retry_after(e))
        raise ProviderError(f"Gemini error: {e}")


async def stream_openai_compat(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    """Generic OpenAI-compatible streaming for openai, codex, deepseek, groq, openrouter, xai, mistral, perplexity, together, cerebras, fireworks, azure, custom."""
    if provider.provider_type == "codex" and provider.auth_type == "oauth" and provider.auth_path:
        async for chunk in _stream_codex_cli(provider, messages, **kw):
            yield chunk
        return

    from openai import AsyncOpenAI, RateLimitError as OAIRateLimit, AuthenticationError as OAIAuth
    creds = _get_credentials(provider)
    api_key = creds.get("api_key") or creds.get("access_token") or "sk-placeholder"
    ptype = provider.provider_type

    base_url = provider.base_url or _OPENAI_COMPAT_URLS.get(ptype)

    if ptype == "azure" and not base_url:
        raise ProviderError("Azure OpenAI requires a base URL (e.g. https://myresource.openai.azure.com/openai/deployments/gpt-4o)")

    model = kw.get("model_override") or provider.model_name or _DEFAULT_MODELS.get(ptype, "gpt-4o")

    extra_headers: dict = {}
    if ptype == "openrouter":
        extra_headers["HTTP-Referer"] = "https://nexora.parendum.com"
        extra_headers["X-Title"] = "Nexora"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
    formatted = [{"role": m["role"], "content": m["content"]} for m in messages]
    if kw.get("system_prompt"):
        formatted.insert(0, {"role": "system", "content": kw["system_prompt"]})

    try:
        _oai_kw: dict = dict(
            model=model,
            messages=formatted,
            stream=True,
            max_tokens=kw.get("max_tokens", 8192),
            extra_headers=extra_headers or None,
        )
        _t = _temp(kw)
        if _t is not None:
            _oai_kw["temperature"] = _t
        # Native tool calling (#214): expose schema-backed tools; structured calls
        # are accumulated across deltas and emitted as a ```tool_calls fence below.
        _tool_keys = kw.get("tool_keys")
        if _tool_keys:
            from src.services.agent_tools.tool_schemas import build_provider_tools
            _otools = build_provider_tools(_tool_keys, "openai")
            if _otools:
                _oai_kw["tools"] = _otools
                _oai_kw["tool_choice"] = "auto"
        # Mode → reasoning effort (think/deep on an OpenAI reasoning model).
        from src.providers.reasoning import openai_reasoning_effort
        _re = openai_reasoning_effort(kw.get("mode"), ptype, model)
        if _re:
            _oai_kw["reasoning_effort"] = _re
        # Try with usage reporting; fall back without the optional extras if the
        # provider/model rejects stream_options and/or reasoning_effort.
        try:
            stream = await client.chat.completions.create(
                stream_options={"include_usage": True}, **_oai_kw,
            )
        except Exception:
            _oai_kw.pop("reasoning_effort", None)
            stream = await client.chat.completions.create(**_oai_kw)
        usage_data = None
        finish_reason = None
        _tc_acc: dict = {}
        _reasoning_open = False
        async for chunk in stream:
            if chunk.usage:
                usage_data = chunk.usage
            if not chunk.choices:
                continue
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
            _delta_obj = chunk.choices[0].delta
            # Provider-native reasoning (DeepSeek `reasoning_content`, OpenRouter /
            # others `reasoning`): surface it wrapped in <think> so the UI renders it
            # as a collapsible thinking block. Free — just relays what the provider
            # already streamed; no-op when the field is absent.
            _rc = getattr(_delta_obj, "reasoning_content", None) or getattr(_delta_obj, "reasoning", None)
            if _rc:
                if not _reasoning_open:
                    yield "<think>"
                    _reasoning_open = True
                yield _rc
            _delta_tcs = getattr(_delta_obj, "tool_calls", None)
            if _delta_tcs:
                from src.providers.native_tools import accumulate_openai_tool_calls
                accumulate_openai_tool_calls(_tc_acc, _delta_tcs)
            delta = _delta_obj.content
            if delta:
                if _reasoning_open:
                    yield "</think>\n"
                    _reasoning_open = False
                yield delta
        if _reasoning_open:
            yield "</think>"
        if _tc_acc:
            from src.providers.native_tools import finalize_openai_tool_calls, fence_from_calls
            _native_calls = finalize_openai_tool_calls(_tc_acc)
            if _native_calls:
                yield fence_from_calls(_native_calls)
        from src.providers.cli_streams import _metadata_event
        _meta: dict = {"provider": ptype, "model": model}
        if usage_data:
            _meta["usage"] = {
                "input_tokens": usage_data.prompt_tokens or 0,
                "output_tokens": usage_data.completion_tokens or 0,
            }
        # Surface truncation so the router can auto-continue instead of leaving the
        # reply cut off mid-output (a hit on max_tokens reports finish_reason="length").
        if finish_reason:
            _meta["finish_reason"] = finish_reason
        if usage_data or finish_reason:
            yield _metadata_event(_meta)
    except OAIRateLimit as e:
        err_code = getattr(e, "code", None) or ""
        body = getattr(e, "body", {}) or {}
        err_body: dict = body if isinstance(body, dict) else {}
        if not err_code:
            err_code = err_body.get("error", {}).get("code", "") or err_body.get("error", {}).get("type", "")
        if err_code == "insufficient_quota":
            raise ProviderError(f"{ptype}: quota exceeded for this model — pick a different model")
        # Detect provider-specific long-duration usage limits (e.g. OpenCode 5-hour cap)
        # and extract the reset time so the router sets an appropriate cooldown.
        err_type = err_body.get("error", {}).get("type", "")
        cooldown_hint: int | None = None
        if err_type in ("GoUsageLimitError", "FreeUsageLimitError"):
            import re as _re
            msg = err_body.get("error", {}).get("message", "")
            # Try "Xhr Ymin" format
            m = _re.search(r"(\d+)hr\s*(\d+)min", msg)
            if m:
                cooldown_hint = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + 60
            else:
                # Try "Resets in N days" or "N day(s)"
                md = _re.search(r"(\d+)\s*day", msg, _re.IGNORECASE)
                if md:
                    cooldown_hint = int(md.group(1)) * 86400
                else:
                    # FreeUsageLimitError: daily free tier — default 24h
                    # GoUsageLimitError without time info: default 5h
                    cooldown_hint = 86400 if err_type == "FreeUsageLimitError" else 5 * 3600
        # OpenAI per-minute TPM/RPM bursts put the reset in the MESSAGE body
        # ("Please try again in 68ms" / "1.2s" / "2m"), not a Retry-After header. Parse
        # it so the cooldown is the real (often sub-second) value instead of the long
        # default — the router then briefly waits and retries instead of failing the task.
        if cooldown_hint is None:
            import re as _re2
            _msg = err_body.get("error", {}).get("message", "") or (e.message if hasattr(e, "message") else str(e))
            _m = _re2.search(r"try again in\s*([\d.]+)\s*(ms|s|m)\b", _msg, _re2.IGNORECASE)
            if _m:
                _val = float(_m.group(1)); _unit = _m.group(2).lower()
                _secs = _val / 1000 if _unit == "ms" else (_val * 60 if _unit == "m" else _val)
                # round sub-second up to a small floor so the retry actually clears the window
                cooldown_hint = max(_secs, 0.5)
        # A Retry-After / ratelimit-reset header (when present) is the most accurate
        # signal; fall back to the parsed provider-specific usage-limit hint.
        raise RateLimitError(
            f"{ptype}: {e.message if hasattr(e, 'message') else str(e)}",
            cooldown_seconds=parse_retry_after(e) or cooldown_hint,
        )
    except OAIAuth as e:
        raise ProviderError(f"{ptype} auth error: {e}")
    except Exception as e:
        raise ProviderError(f"{ptype} error: {e}")


async def stream_ollama(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    import httpx
    base_url = provider.base_url or "http://localhost:11434"
    model = provider.model_name or _DEFAULT_MODELS.get("ollama", "")
    formatted = [{"role": m["role"], "content": m["content"]} for m in messages]

    _options: dict = {}
    _t = _temp(kw)
    if _t is not None:
        _options["temperature"] = _t
    if kw.get("max_tokens"):
        _options["num_predict"] = kw["max_tokens"]
    _body: dict = {"model": model, "messages": formatted, "stream": True}
    if _options:
        _body["options"] = _options

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            async with client.stream(
                "POST", f"{base_url}/api/chat",
                json=_body,
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if content := data.get("message", {}).get("content"):
                            yield content
        except Exception as e:
            raise ProviderError(f"Ollama error: {e}")


async def stream_vertex_ai(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    """Google Vertex AI — Gemini models via OpenAI-compatible endpoint using google-auth."""
    import asyncio
    import json as _json

    creds_dict = _get_credentials(provider)
    project  = creds_dict.get("project_id") or creds_dict.get("project", "")
    location = creds_dict.get("location") or creds_dict.get("region") or "us-central1"
    model_name = kw.get("model_override") or provider.model_name or _DEFAULT_MODELS.get("vertex_ai", "google/gemini-2.0-flash-001")
    sa_json_str = creds_dict.get("service_account_json") or creds_dict.get("api_key", "")

    if not project:
        raise ProviderError("Vertex AI requires project_id in credentials JSON")

    # Obtain a short-lived Google OAuth2 bearer token from service account JSON
    def _get_token() -> str:
        from google.oauth2 import service_account as _sa
        from google.auth.transport.requests import Request as _Request
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        if sa_json_str and sa_json_str.strip().startswith("{"):
            sa_info = _json.loads(sa_json_str)
            gc = _sa.Credentials.from_service_account_info(sa_info, scopes=scopes)
        else:
            # Fall back to Application Default Credentials
            import google.auth
            gc, _ = google.auth.default(scopes=scopes)
        gc.refresh(_Request())
        return gc.token

    try:
        token = await asyncio.to_thread(_get_token)
    except Exception as e:
        raise ProviderError(f"Vertex AI auth error: {e}")

    # Vertex AI OpenAI-compatible endpoint
    base_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{location}/endpoints/openapi"

    from openai import AsyncOpenAI, RateLimitError as OAIRateLimit, AuthenticationError as OAIAuth
    client = AsyncOpenAI(api_key=token, base_url=base_url, max_retries=0)

    formatted = [{"role": m["role"], "content": m["content"]} for m in messages]
    if kw.get("system_prompt"):
        formatted.insert(0, {"role": "system", "content": kw["system_prompt"]})

    _vx_kw: dict = dict(
        model=model_name,
        messages=formatted,
        stream=True,
        max_tokens=kw.get("max_tokens", 8192),
    )
    _t = _temp(kw)
    if _t is not None:
        _vx_kw["temperature"] = _t
    try:
        stream = await client.chat.completions.create(**_vx_kw)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except OAIRateLimit as e:
        raise RateLimitError(f"Vertex AI rate limit: {e}", cooldown_seconds=parse_retry_after(e))
    except OAIAuth as e:
        raise ProviderError(f"Vertex AI auth error: {e}")
    except Exception as e:
        err = str(e).lower()
        if "quota" in err or "rate" in err or "resource_exhausted" in err:
            raise RateLimitError(f"Vertex AI rate limit: {e}")
        raise ProviderError(f"Vertex AI error: {e}")


async def stream_bedrock(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    """AWS Bedrock converse-stream API via boto3."""
    import asyncio
    import boto3
    import json as _json

    creds = _get_credentials(provider)
    access_key = creds.get("access_key") or creds.get("aws_access_key_id", "")
    secret_key = creds.get("secret_key") or creds.get("aws_secret_access_key", "")
    region = creds.get("region") or provider.base_url or "us-east-1"
    model = kw.get("model_override") or provider.model_name or _DEFAULT_MODELS.get("bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    kw_boto: dict = {"region_name": region}
    if access_key and secret_key:
        kw_boto["aws_access_key_id"] = access_key
        kw_boto["aws_secret_access_key"] = secret_key

    # Separate system messages from conversation
    system_prompt = kw.get("system_prompt")
    system_blocks = [{"text": system_prompt}] if system_prompt else []
    converse_msgs = [
        {"role": m["role"], "content": [{"text": m["content"]}]}
        for m in messages if m["role"] != "system" and m.get("content")
    ]

    max_tokens = kw.get("max_tokens", 8192)
    _inference: dict = {"maxTokens": max_tokens}
    _t = _temp(kw)
    if _t is not None:
        _inference["temperature"] = _t

    def _call():
        client = boto3.client("bedrock-runtime", **kw_boto)
        extra: dict = {}
        if system_blocks:
            extra["system"] = system_blocks
        return client.converse_stream(
            modelId=model,
            messages=converse_msgs,
            inferenceConfig=_inference,
            **extra,
        )

    try:
        response = await asyncio.to_thread(_call)
    except Exception as e:
        if _is_bedrock_throttle(e):
            raise RateLimitError(f"Bedrock rate limit: {e}", cooldown_seconds=parse_retry_after(e))
        raise ProviderError(f"Bedrock error: {e}")

    input_tokens = 0
    output_tokens = 0
    stop_reason = None
    try:
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield text
            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason")
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                input_tokens = usage.get("inputTokens", 0)
                output_tokens = usage.get("outputTokens", 0)
    except Exception as e:
        raise ProviderError(f"Bedrock stream error: {e}")

    from src.providers.cli_streams import _metadata_event
    meta: dict = {"provider": "bedrock", "model": model}
    if input_tokens or output_tokens:
        meta["usage"] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    # Bedrock Converse reports stopReason="max_tokens" on truncation → auto-continue.
    if stop_reason == "max_tokens":
        meta["finish_reason"] = "length"
    yield _metadata_event(meta)


# ── Provider registry — built dynamically from seeds/providers/ ───────────────

_STREAM_FN_MAP = {
    "claude":        stream_claude,
    "gemini":        stream_gemini,
    "ollama":        stream_ollama,
    "openai_compat": stream_openai_compat,
    "bedrock":       stream_bedrock,
    "vertex_ai":     stream_vertex_ai,
}

PROVIDER_STREAMS: dict = {}


def _build_provider_registry() -> None:
    """Populate module-level lookup dicts and PROVIDER_STREAMS from provider seed files.
    Called once at module load after all stream functions are defined."""
    from src.seeds.loader import get_all_providers
    global PROVIDER_STREAMS

    for p in get_all_providers():
        key = p.get("key", "")
        if not key:
            continue
        if p.get("base_url") is not None:
            _OPENAI_COMPAT_URLS[key] = p["base_url"]
        if p.get("default_model"):
            _DEFAULT_MODELS[key] = p["default_model"]
        if p.get("stream_type") == "openai_compat":
            _OPENAI_COMPAT_TYPES.add(key)

    PROVIDER_STREAMS = {
        key: fn
        for p in get_all_providers()
        if (key := p.get("key", "")) and (fn := _STREAM_FN_MAP.get(p.get("stream_type", "")))
    }


_build_provider_registry()


# ── Main fallback chain ───────────────────────────────────────────────────────


def _is_durably_cooling(provider: Provider) -> bool:
    """Durable (DB-backed) cooldown gate complementing the fast Redis check.

    Survives a Redis flush/restart: an account whose ``cooling_until`` is still in
    the future is skipped even if the ephemeral Redis key is gone.
    """
    cu = getattr(provider, "cooling_until", None)
    if not cu:
        return False
    from datetime import datetime, timezone
    if cu.tzinfo is None:
        cu = cu.replace(tzinfo=timezone.utc)
    return cu > datetime.now(timezone.utc)

async def stream_response(
    providers: list[tuple[Provider, str | None]],
    messages: list[dict],
    *,
    status_events: bool = False,
    **kwargs,
) -> AsyncIterator[str]:
    """Try each (provider, step_model_override) pair in order, falling back on rate limits.

    When ``status_events`` is set, the generator also yields ``_STATUS_PREFIX`` lines
    describing the live fallback chain (which provider is being tried, failovers,
    empty-retries). Only opt-in callers (the chat WebSocket) consume these; other
    callers (titles, telegram, sub-agents) leave it False so the sentinel never leaks
    into accumulated text.
    """
    # Internal: how many times we've already waited-and-retried the whole chain after a
    # short rate-limit exhaustion (popped so it never reaches the provider adapters).
    _rl_retries = kwargs.pop("_rl_retries", 0)
    last_error = None
    _min_rl_cd: float | None = None  # soonest rate-limit reset seen this pass (for wait-and-retry)
    _tried_any = False  # becomes True after the first attempt → later picks are "failovers"

    # Native tool calling (#214): resolve the agent's schema-backed tools once and
    # pass their keys to the adapters (which convert structured calls back into the
    # ```tool_calls fence). No-op when the flag is off → text-fence path unchanged.
    from src.core.config import get_settings as _get_settings_nt
    if _get_settings_nt().native_tools_enabled and "tool_keys" not in kwargs:
        _aid = kwargs.get("agent_id")
        _cid = kwargs.get("chat_id")
        if _aid and _cid:
            try:
                from src.services.agent_tools.tool_permissions import _get_agent_enabled_tools
                from src.providers.native_tools import all_schemaed_tool_keys
                _enabled = await _get_agent_enabled_tools(_aid, _cid)
                kwargs["tool_keys"] = sorted(_enabled) if _enabled else all_schemaed_tool_keys()
            except Exception as _nt_exc:
                logger.debug("native tool_keys resolve failed: %s", _nt_exc)

    def _status(label: str) -> str | None:
        return _status_event(label) if status_events else None

    for provider, step_model in providers:
        if not provider.is_active:
            continue
        # Skip a cooling/exhausted account: fast ephemeral Redis gate OR the durable
        # DB cooling_until (so a cooldown survives a Redis flush/restart). Failover
        # then advances to the next account of the same type, then the next type.
        if await is_cooling(provider.id) or _is_durably_cooling(provider):
            logger.info(f"Provider {provider.name} cooling, skipping")
            _s = _status(f"{provider.name} cooling down — skipping")
            if _s:
                yield _s
            continue

        stream_fn = PROVIDER_STREAMS.get(provider.provider_type)
        if not stream_fn:
            logger.warning(f"Unknown provider type: {provider.provider_type}")
            continue

        effective = copy.copy(provider)
        if step_model:
            effective.model_name = step_model

        _model_lbl = effective.model_name or "default"
        _s = _status(
            (f"Switching to {provider.name}" if _tried_any else f"Using {provider.name}")
            + f" · {_model_lbl}"
        )
        if _s:
            yield _s
        _tried_any = True

        try:
            logger.info(f"Using provider: {provider.name} ({provider.provider_type}, model={effective.model_name or 'default'})")
            from src.core.config import get_settings as _get_settings
            _settings = _get_settings()
            _max_continues = _settings.max_truncation_continuations
            _max_empty_retries = _settings.max_empty_retries
            content_yielded = False
            _usage_tokens = 0  # budget tally (#235) — accumulated from usage metadata
            # #220: prompt-cache breakpoint handling. Only the Anthropic adapter keeps
            # the sentinel (and splits the system block on it for cache_control);
            # every other provider has it stripped so it can never leak into a prompt.
            # No-op when the flag is off (the sentinel is never emitted).
            # Only the Anthropic API-key path supports cache_control blocks; the
            # OAuth/CLI claude path renders a plain prompt and can't cache, so it is
            # treated like any other provider (sentinel stripped).
            if (_settings.prompt_cache_enabled and effective.provider_type == "claude"
                    and effective.auth_type != "oauth"):
                _pmsgs = messages
                _call_kwargs = {**kwargs, "prompt_cache": True}
            else:
                from src.providers.prompt_cache import strip_sentinel_messages as _strip_pc
                _pmsgs = _strip_pc(messages)
                _call_kwargs = kwargs
            # Retry-on-empty: flaky weak models (e.g. OpenCode Go fallback when Claude
            # OAuth is down) intermittently stream ZERO content — one such empty turn
            # used to kill the whole chat. Retry the SAME provider a few times. Safe
            # because we only retry while content_yielded is False (nothing emitted
            # downstream yet), so a later success can't duplicate earlier output.
            for _empty_attempt in range(_max_empty_retries + 1):
                # Auto-continue a reply truncated at max_tokens (finish_reason="length"):
                # re-call with the partial + a "continue where you left off" instruction so
                # the user gets the full response (and the watchdog doesn't mark a truncated
                # turn as <final/>). Capped to avoid runaway loops.
                cont_messages = list(_pmsgs)
                partial_acc = ""
                continues = 0
                while True:
                    finish_reason = None
                    turn_text = ""
                    async for chunk in stream_fn(effective, cont_messages, **_call_kwargs):
                        if chunk.startswith(_METADATA_PREFIX):
                            try:
                                _m = json.loads(chunk[len(_METADATA_PREFIX):])
                                if _m.get("finish_reason"):
                                    finish_reason = _m["finish_reason"]
                                _u = _m.get("usage") or {}
                                _usage_tokens += int(_u.get("input_tokens", 0) or 0) + int(_u.get("output_tokens", 0) or 0)
                            except Exception:
                                pass
                            # Metadata (usage/finish_reason) trails content in every stream
                            # fn. Emit it only for the first content-bearing turn — so an
                            # empty turn we're about to retry emits no usage, and continuation
                            # turns don't double-emit. Account-name metadata is added at the end.
                            if continues == 0 and content_yielded:
                                yield chunk
                            continue
                        content_yielded = True
                        turn_text += chunk
                        yield chunk
                    if finish_reason == "length" and turn_text and continues < _max_continues:
                        continues += 1
                        partial_acc += turn_text
                        logger.info(
                            f"Provider {provider.name} truncated at max_tokens — "
                            f"auto-continuing ({continues}/{_max_continues})"
                        )
                        from src.seeds.loader import get_prompt as _get_prompt
                        try:
                            _cont_instr = _get_prompt("continue_truncated").strip()
                        except Exception:
                            _cont_instr = "Continue exactly where you left off without repeating anything."
                        cont_messages = list(_pmsgs) + [
                            {"role": "assistant", "content": partial_acc},
                            {"role": "user", "content": _cont_instr},
                        ]
                        continue
                    break
                if content_yielded:
                    break  # got a real response — stop retrying
                if _empty_attempt < _max_empty_retries:
                    logger.warning(
                        f"Provider {provider.name} streamed empty — retrying same provider "
                        f"({_empty_attempt + 1}/{_max_empty_retries})"
                    )
                    _s = _status(
                        f"{provider.name} returned empty — retrying "
                        f"({_empty_attempt + 1}/{_max_empty_retries})"
                    )
                    if _s:
                        yield _s
                    await asyncio.sleep(0.6)
            if content_yielded:
                from src.providers.cli_streams import _metadata_event
                yield _metadata_event({"account_name": provider.name})
                _fire_metering(kwargs.get("org_id"))
                record_provider_success(provider.id)
                # Budget tally (#235): record this turn's tokens for the org.
                try:
                    from src.services.budget import record_usage as _rec_budget
                    await _rec_budget(kwargs.get("org_id"), _usage_tokens)
                except Exception:
                    pass
                return
            logger.warning(f"Provider {provider.name} returned an empty response, trying next")
            _s = _status(f"{provider.name} returned empty — trying next provider")
            if _s:
                yield _s
            last_error = ProviderError(f"{provider.name} returned an empty response")
            record_provider_failure(provider.id, "empty response", rate_limited=False)
        except RateLimitError as e:
            # Prefer the provider's own cooldown hint (adapters parse Retry-After /
            # ratelimit-reset headers into cooldown_seconds), else the per-account default.
            cooldown = getattr(e, "cooldown_seconds", None) or provider.cooldown_seconds
            logger.warning(f"Rate limit on {provider.name}: {e} (cooling {cooldown}s)")
            _s = _status(f"{provider.name} rate-limited — failing over")
            if _s:
                yield _s
            await set_cooling(provider.id, cooldown)
            record_provider_failure(provider.id, str(e), rate_limited=True, cooldown_seconds=cooldown)
            last_error = e
            # Track the soonest reset so an all-rate-limited chain can wait-and-retry
            # rather than failing the turn (a per-minute TPM burst clears in seconds).
            try:
                _cd = float(cooldown or 0)
                if _cd > 0:
                    _min_rl_cd = _cd if _min_rl_cd is None else min(_min_rl_cd, _cd)
            except (TypeError, ValueError):
                pass
        except ProviderError as e:
            logger.warning(f"Provider error on {provider.name}: {e}")
            _s = _status(f"{provider.name} failed — failing over")
            if _s:
                yield _s
            last_error = e
            # Record every provider failure so health/circuit state is accurate (not
            # just auth errors): consecutive non-rate failures eventually mark the
            # account exhausted so it's skipped for a while.
            record_provider_failure(provider.id, str(e), rate_limited=False)

    # Whole chain exhausted. If every viable account was rate-limited with a SHORT reset,
    # waiting and retrying beats failing the turn — failover can't escape a per-API-org TPM
    # limit shared by sibling accounts, but the window clears in seconds. Bounded.
    from src.core.config import get_settings as _gs_rl
    _rl_cfg = _gs_rl()
    if (
        _min_rl_cd is not None
        and _rl_retries < _rl_cfg.rate_limit_chain_retries
        and _min_rl_cd <= _rl_cfg.rate_limit_retry_max_wait_seconds
    ):
        _wait = min(_min_rl_cd, float(_rl_cfg.rate_limit_retry_max_wait_seconds)) + 0.1
        logger.info(
            "[router] all accounts rate-limited (soonest reset ~%.2fs) — waiting then retrying "
            "chain (attempt %d/%d)", _min_rl_cd, _rl_retries + 1, _rl_cfg.rate_limit_chain_retries
        )
        _s = _status(f"All accounts rate-limited — waiting {_wait:.1f}s then retrying")
        if _s:
            yield _s
        await asyncio.sleep(_wait)
        async for _chunk in stream_response(
            providers, messages, status_events=status_events, _rl_retries=_rl_retries + 1, **kwargs
        ):
            yield _chunk
        return

    msg = str(last_error) if last_error else "No available providers"
    raise AllProvidersExhausted(msg)
