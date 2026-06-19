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
from src.providers.cli_streams import (
    _METADATA_PREFIX,  # noqa: F401 — re-exported for callers that import it from here
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
        system_prompt = kw.get("system_prompt")
        system_param = (
            [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
            if system_prompt else None
        )
        final_msg = None
        async with client.messages.stream(
            model=model,
            max_tokens=kw.get("max_tokens", 8192),
            messages=_to_anthropic_messages(messages),
            system=system_param,
        ) as stream:
            async for text in stream.text_stream:
                yield text
            try:
                final_msg = await stream.get_final_message()
            except Exception:
                pass
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
        yield _metadata_event(meta)
    except anthropic.RateLimitError:
        raise RateLimitError("Claude rate limit")
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

        async for chunk in client.aio.models.generate_content_stream(
            model=model_name,
            contents=contents,
            config=config or None,
        ):
            if chunk.text:
                yield chunk.text
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
            err = str(e).lower()
            if "quota" in err or "rate" in err or "resource_exhausted" in err:
                raise RateLimitError(f"Gemini rate limit: {e}")
            raise ProviderError(f"Gemini error: {e}")
    except Exception as e:
        err = str(e).lower()
        if "quota" in err or "rate" in err or "resource_exhausted" in err:
            raise RateLimitError(f"Gemini rate limit: {e}")
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
        # Try with usage reporting; fall back silently if provider rejects stream_options
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=formatted,
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=kw.get("max_tokens", 8192),
                extra_headers=extra_headers or None,
            )
        except Exception:
            stream = await client.chat.completions.create(
                model=model,
                messages=formatted,
                stream=True,
                max_tokens=kw.get("max_tokens", 8192),
                extra_headers=extra_headers or None,
            )
        usage_data = None
        async for chunk in stream:
            if chunk.usage:
                usage_data = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        if usage_data:
            from src.providers.cli_streams import _metadata_event
            yield _metadata_event({
                "provider": ptype,
                "model": model,
                "usage": {
                    "input_tokens": usage_data.prompt_tokens or 0,
                    "output_tokens": usage_data.completion_tokens or 0,
                },
            })
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
        raise RateLimitError(
            f"{ptype}: {e.message if hasattr(e, 'message') else str(e)}",
            cooldown_seconds=cooldown_hint,
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

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            async with client.stream(
                "POST", f"{base_url}/api/chat",
                json={"model": model, "messages": formatted, "stream": True},
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

    try:
        stream = await client.chat.completions.create(
            model=model_name,
            messages=formatted,
            stream=True,
            max_tokens=kw.get("max_tokens", 8192),
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except OAIRateLimit as e:
        raise RateLimitError(f"Vertex AI rate limit: {e}")
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

    def _call():
        client = boto3.client("bedrock-runtime", **kw_boto)
        extra: dict = {}
        if system_blocks:
            extra["system"] = system_blocks
        return client.converse_stream(
            modelId=model,
            messages=converse_msgs,
            inferenceConfig={"maxTokens": max_tokens},
            **extra,
        )

    try:
        response = await asyncio.to_thread(_call)
    except Exception as e:
        err = str(e).lower()
        if "throttling" in err or "too many" in err:
            raise RateLimitError(f"Bedrock rate limit: {e}")
        raise ProviderError(f"Bedrock error: {e}")

    input_tokens = 0
    output_tokens = 0
    try:
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield text
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


# ── Provider health tracking ──────────────────────────────────────────────────

def _record_provider_error(provider_id: str, error: str) -> None:
    """Fire-and-forget: persist auth error to providers table."""
    import asyncio as _asyncio
    from datetime import datetime, timezone

    async def _write() -> None:
        try:
            from src.core.database import AsyncSessionLocal
            from sqlalchemy import update as _update
            from src.models.provider import Provider as _P
            async with AsyncSessionLocal() as db:
                await db.execute(
                    _update(_P).where(_P.id == provider_id).values(
                        last_error=error[:500],
                        last_error_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.debug("Failed to record provider error: %s", exc)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_write())
    except Exception:
        pass


def _record_provider_success(provider_id: str) -> None:
    """Fire-and-forget: clear last_error and update last_used_at."""
    import asyncio as _asyncio
    from datetime import datetime, timezone

    async def _write() -> None:
        try:
            from src.core.database import AsyncSessionLocal
            from sqlalchemy import update as _update
            from src.models.provider import Provider as _P
            async with AsyncSessionLocal() as db:
                await db.execute(
                    _update(_P).where(_P.id == provider_id).values(
                        last_error=None,
                        last_error_at=None,
                        last_used_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.debug("Failed to record provider success: %s", exc)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_write())
    except Exception:
        pass


# ── Main fallback chain ───────────────────────────────────────────────────────

async def stream_response(
    providers: list[tuple[Provider, str | None]],
    messages: list[dict],
    **kwargs,
) -> AsyncIterator[str]:
    """Try each (provider, step_model_override) pair in order, falling back on rate limits."""
    last_error = None

    for provider, step_model in providers:
        if not provider.is_active:
            continue
        if await is_cooling(provider.id):
            logger.info(f"Provider {provider.name} cooling, skipping")
            continue

        stream_fn = PROVIDER_STREAMS.get(provider.provider_type)
        if not stream_fn:
            logger.warning(f"Unknown provider type: {provider.provider_type}")
            continue

        effective = copy.copy(provider)
        if step_model:
            effective.model_name = step_model

        try:
            logger.info(f"Using provider: {provider.name} ({provider.provider_type}, model={effective.model_name or 'default'})")
            content_yielded = False
            async for chunk in stream_fn(effective, messages, **kwargs):
                if not chunk.startswith(_METADATA_PREFIX):
                    content_yielded = True
                yield chunk
            if content_yielded:
                from src.providers.cli_streams import _metadata_event
                yield _metadata_event({"account_name": provider.name})
                _fire_metering(kwargs.get("org_id"))
                _record_provider_success(provider.id)
                return
            logger.warning(f"Provider {provider.name} returned an empty response, trying next")
            last_error = ProviderError(f"{provider.name} returned an empty response")
        except RateLimitError as e:
            cooldown = getattr(e, "cooldown_seconds", None) or provider.cooldown_seconds
            logger.warning(f"Rate limit on {provider.name}: {e} (cooling {cooldown}s)")
            await set_cooling(provider.id, cooldown)
            last_error = e
        except ProviderError as e:
            logger.warning(f"Provider error on {provider.name}: {e}")
            last_error = e
            # Auth errors (401/403/auth keyword) recorded so the UI can surface them
            err_str = str(e).lower()
            if any(w in err_str for w in ("auth", "401", "403", "unauthorized", "invalid api key", "permission")):
                _record_provider_error(provider.id, str(e))

    msg = str(last_error) if last_error else "No available providers"
    raise AllProvidersExhausted(msg)
