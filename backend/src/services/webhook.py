"""Outbound webhook firing with HMAC-SHA256 signing and exponential-backoff retry.

When sync_response is enabled on the chat the agent awaits the HTTP response (up to
sync_timeout seconds) and the JSON body is returned so the orchestrator can inject
it back into the conversation as a tool result.  On timeout or error a descriptive
error string is returned instead.
"""
import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from src.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0
_SYNC_TIMEOUT_MAX = 30


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _build_headers(body: bytes, secret: str | None) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "Nexora-Webhook/1.0"}
    if secret:
        headers["X-Nexora-Signature"] = f"sha256={_sign(body, secret)}"
    return headers


async def _post_with_retry(url: str, payload: dict, secret: str | None) -> None:
    """Fire-and-forget POST with exponential-backoff retry (no response needed)."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = _build_headers(body, secret)

    delay = _RETRY_BASE_SECONDS
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                r = await client.post(url, content=body, headers=headers)
                if r.status_code < 500:
                    if r.status_code >= 400:
                        logger.warning(
                            "Webhook %s returned %s (attempt %s) — not retrying client error",
                            url, r.status_code, attempt,
                        )
                    return
                logger.warning("Webhook %s returned %s (attempt %s/%s)", url, r.status_code, attempt, _MAX_RETRIES)
            except Exception as exc:
                logger.warning("Webhook %s error (attempt %s/%s): %s", url, attempt, _MAX_RETRIES, exc)

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= 2


async def _post_sync(url: str, payload: dict, secret: str | None, timeout: int) -> dict | str:
    """Synchronous POST: await the response and return parsed JSON body (or an error string).

    The caller receives either:
      - a dict — the parsed JSON body from the endpoint
      - a str  — an error description (timeout, non-2xx, invalid JSON, network error)
    """
    clamped_timeout = min(max(1, timeout), _SYNC_TIMEOUT_MAX)
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = _build_headers(body, secret)

    try:
        async with httpx.AsyncClient(timeout=float(clamped_timeout)) as client:
            r = await client.post(url, content=body, headers=headers)
    except httpx.TimeoutException:
        logger.warning("Webhook %s sync timeout after %ss", url, clamped_timeout)
        return f"Webhook timeout: no response from {url} within {clamped_timeout}s"
    except Exception as exc:
        logger.warning("Webhook %s sync error: %s", url, exc)
        return f"Webhook error: {exc}"

    if r.status_code >= 400:
        return f"Webhook returned HTTP {r.status_code}: {r.text[:200]}"

    # Attempt JSON parse; fall back to raw text wrapped in a dict
    try:
        return r.json()
    except Exception:
        return {"response": r.text}


async def fire_webhook(
    chat_id: str,
    message_id: str,
    content: str,
    agent_id: str | None,
    timestamp: str | None = None,
) -> dict | str | None:
    """Load webhook config from chat row and POST the event payload.

    Returns:
      - None          if no webhook is configured, or sync_response is False (fire-and-forget)
      - dict | str    if sync_response is True — the parsed response body or an error description
    """
    from sqlalchemy import select
    from src.models.chat import Chat

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(
                Chat.webhook_url,
                Chat.webhook_secret,
                Chat.sync_response,
                Chat.sync_timeout,
            ).where(Chat.id == chat_id)
        )
        row = r.one_or_none()

    if not row or not row.webhook_url:
        return None

    payload = {
        "event": "message.completed",
        "chat_id": chat_id,
        "message_id": message_id,
        "content": content,
        "agent_id": agent_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }

    if row.sync_response:
        return await _post_sync(row.webhook_url, payload, row.webhook_secret, row.sync_timeout)

    # Fire-and-forget
    asyncio.create_task(_post_with_retry(row.webhook_url, payload, row.webhook_secret))
    return None


async def fire_webhook_and_inject(
    chat_id: str,
    message_id: str,
    content: str,
    agent_id: str | None,
    org_id: str | None,
    agent_name: str | None,
    provider_chain_id: str | None,
    timestamp: str | None = None,
) -> None:
    """Fire the outbound webhook.

    When sync_response is enabled, awaits the response (up to sync_timeout seconds),
    saves it as a system injection message, and re-invokes the agent via
    _resume_with_tool_results so the agent can process the webhook's reply.

    When sync_response is disabled, fires and forgets in the background.
    """
    result = await fire_webhook(
        chat_id=chat_id,
        message_id=message_id,
        content=content,
        agent_id=agent_id,
        timestamp=timestamp,
    )

    if result is None:
        # Either no webhook configured or fire-and-forget already dispatched
        return

    # Sync response received — inject into the conversation
    import uuid as _uuid
    from src.models.chat import Message

    if isinstance(result, dict):
        import json as _json
        injection_text = (
            "<system_observation type=\"webhook_response\">\n"
            "The webhook endpoint returned the following response. "
            "Incorporate it into your reply.\n\n"
            f"```json\n{_json.dumps(result, indent=2)}\n```\n"
            "</system_observation>"
        )
        tool_result_entry = {"tool": "webhook_response", "data": result}
    else:
        # Error string
        injection_text = (
            "<system_observation type=\"webhook_response\">\n"
            f"Webhook call result: {result}\n"
            "</system_observation>"
        )
        tool_result_entry = {"tool": "webhook_response", "error": result}

    injection_id = str(_uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(Message(
            id=injection_id,
            chat_id=chat_id,
            role="user",
            content=injection_text,
            excluded=True,
            metadata_={"kind": "webhook_response_injection"},
        ))
        await db.commit()

    logger.info("Webhook sync response injected for chat=%s message=%s", chat_id, injection_id)

    if org_id:
        from src.services.orchestrator import _resume_with_tool_results
        asyncio.create_task(
            _resume_with_tool_results(
                chat_id=chat_id,
                org_id=org_id,
                agent_id=agent_id,
                agent_name=agent_name,
                tool_results=[tool_result_entry],
                provider_chain_id=provider_chain_id,
            )
        )
