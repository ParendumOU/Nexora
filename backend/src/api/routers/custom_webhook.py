"""Custom inbound webhook endpoint for Sentry, PagerDuty, Datadog, etc."""
import logging

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.webhook_rule import WebhookRule
from src.services.webhook_dispatch import dispatch_webhook_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/custom/{org_id}/{secret}")
async def custom_webhook(org_id: str, secret: str, request: Request):
    """Receive a custom webhook and dispatch it to matching rules."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

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
