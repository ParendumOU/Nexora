"""Webhook rules — CRUD + trigger log."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.webhook_rule import WebhookRule, WebhookRuleTrigger
from src.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook-rules", tags=["webhook-rules"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class WebhookRuleCreate(BaseModel):
    source: str
    event_type: str
    filter_json: dict | None = None
    agent_id: str
    task_title_template: str
    task_description_template: str | None = None
    webhook_secret: str | None = None
    project_id: str | None = None
    is_active: bool = True


class WebhookRuleUpdate(BaseModel):
    source: str | None = None
    event_type: str | None = None
    filter_json: dict | None = None
    agent_id: str | None = None
    task_title_template: str | None = None
    task_description_template: str | None = None
    webhook_secret: str | None = None
    project_id: str | None = None
    is_active: bool | None = None


def _rule_dict(r: WebhookRule) -> dict:
    return {
        "id": r.id,
        "org_id": r.org_id,
        "project_id": r.project_id,
        "source": r.source,
        "event_type": r.event_type,
        "filter_json": r.filter_json,
        "agent_id": r.agent_id,
        "task_title_template": r.task_title_template,
        "task_description_template": r.task_description_template,
        "webhook_secret": r.webhook_secret,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _trigger_dict(t: WebhookRuleTrigger) -> dict:
    return {
        "id": t.id,
        "rule_id": t.rule_id,
        "event_type": t.event_type,
        "task_id": t.task_id,
        "payload_summary": t.payload_summary,
        "created_at": t.created_at.isoformat(),
    }


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[dict])
async def list_webhook_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(WebhookRule)
        .where(WebhookRule.org_id == org_id)
        .order_by(WebhookRule.created_at.desc())
    )
    return [_rule_dict(rule) for rule in r.scalars().all()]


@router.post("", status_code=201, response_model=dict)
async def create_webhook_rule(
    req: WebhookRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    rule = WebhookRule(
        id=str(uuid.uuid4()),
        org_id=org_id,
        project_id=req.project_id,
        source=req.source,
        event_type=req.event_type,
        filter_json=req.filter_json,
        agent_id=req.agent_id,
        task_title_template=req.task_title_template,
        task_description_template=req.task_description_template,
        webhook_secret=req.webhook_secret,
        is_active=req.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_dict(rule)


@router.get("/{rule_id}", response_model=dict)
async def get_webhook_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
    )
    rule = r.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Webhook rule not found")
    return _rule_dict(rule)


@router.put("/{rule_id}", response_model=dict)
async def update_webhook_rule(
    rule_id: str,
    req: WebhookRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
    )
    rule = r.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Webhook rule not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return _rule_dict(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_webhook_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
    )
    rule = r.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Webhook rule not found")
    await db.delete(rule)
    await db.commit()


@router.get("/{rule_id}/log", response_model=list[dict])
async def get_webhook_rule_log(
    rule_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Webhook rule not found")
    r2 = await db.execute(
        select(WebhookRuleTrigger)
        .where(WebhookRuleTrigger.rule_id == rule_id)
        .order_by(WebhookRuleTrigger.created_at.desc())
        .limit(limit)
    )
    return [_trigger_dict(t) for t in r2.scalars().all()]
