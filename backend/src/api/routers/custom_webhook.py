"""Custom inbound webhook endpoint for Sentry, PagerDuty, Datadog, etc."""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.webhook_rule import WebhookRule
from src.services.webhook_dispatch import dispatch_webhook_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


def _verify_signature(raw_body: bytes, secret: str, header_sig: str) -> bool:
    """HMAC-SHA256 of the raw body keyed by the rule secret, GitHub-style
    `sha256=<hex>`. Accepts a bare hex digest too. Constant-time compare."""
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = header_sig.strip()
    if not provided.startswith("sha256="):
        provided = "sha256=" + provided
    return hmac.compare_digest(expected, provided)


@router.post("/custom/{org_id}/{secret}")
async def custom_webhook(org_id: str, secret: str, request: Request):
    """Receive a custom webhook and dispatch it to matching rules.

    Auth has two layers (#182):
      1. The path `{secret}` must match an active custom rule (shared secret).
      2. If the sender signs the body (`X-Webhook-Signature` / `X-Hub-Signature-256`),
         the HMAC-SHA256 of the raw body keyed by that secret is verified, giving
         payload integrity. Senders that don't sign keep working (path secret only).
    """
    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    async with AsyncSessionLocal() as db:
        # Verify at least one active custom rule matches this org + secret
        r = await db.execute(
            select(WebhookRule).where(
                WebhookRule.org_id == org_id,
                WebhookRule.source == "custom",
                WebhookRule.webhook_secret == secret,
                WebhookRule.is_active.is_(True),
            )
        )
        rules = r.scalars().all()

    if not rules:
        raise HTTPException(status_code=403, detail="Invalid secret or no active rules")

    # Optional body-integrity check: reject a present-but-wrong signature.
    sig = request.headers.get("x-webhook-signature") or request.headers.get("x-hub-signature-256")
    if sig and not _verify_signature(raw, secret, sig):
        logger.warning(f"[custom_webhook] bad signature for org {org_id}")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    event_type = payload.get("event_type", payload.get("type", "custom"))
    event_data = {str(k): v for k, v in payload.items()}

    async with AsyncSessionLocal() as db:
        await dispatch_webhook_event(
            db=db,
            org_id=org_id,
            project_id=None,
            source="custom",
            event_type=event_type,
            event_data=event_data,
        )

    logger.info(f"[custom_webhook] dispatched event '{event_type}' for org {org_id}")
    return {"ok": True}
