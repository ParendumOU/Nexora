"""Dispatch incoming webhook events to agents via matching WebhookRule records."""
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.webhook_rule import WebhookRule, WebhookRuleTrigger
from src.services.event_dispatcher import dispatch_event_to_agent

logger = logging.getLogger(__name__)


def _render_template(template: str, event_data: dict) -> str:
    """Replace {{event.key}} placeholders with values from event_data."""
    def _sub(m: re.Match) -> str:
        return str(event_data.get(m.group(1), ""))
    return re.sub(r"\{\{event\.([^}]+)\}\}", _sub, template)


def _match_filter(filter_json: dict | None, event_data: dict) -> bool:
    """Return True if all filter_json conditions are satisfied by event_data."""
    if not filter_json:
        return True
    for key, expected in filter_json.items():
        actual = event_data.get(key)
        if isinstance(expected, list):
            if isinstance(actual, list):
                if not any(e in actual for e in expected):
                    return False
            elif actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


async def dispatch_webhook_event(
    db: AsyncSession,
    org_id: str,
    project_id: str | None,
    source: str,
    event_type: str,
    event_data: dict,
) -> None:
    """Find matching active WebhookRules and dispatch a task for each."""
    r = await db.execute(
        select(WebhookRule).where(
            WebhookRule.org_id == org_id,
            WebhookRule.source == source,
            WebhookRule.event_type == event_type,
            WebhookRule.is_active.is_(True),
        )
    )
    rules = r.scalars().all()

    for rule in rules:
        if not _match_filter(rule.filter_json, event_data):
            continue

        title = _render_template(rule.task_title_template, event_data)
        description = _render_template(rule.task_description_template or "", event_data)

        task_id = await dispatch_event_to_agent(
            org_id=org_id,
            project_id=project_id or rule.project_id,
            agent_id=rule.agent_id,
            event_title=title,
            event_description=description,
        )

        trigger = WebhookRuleTrigger(
            id=str(uuid.uuid4()),
            rule_id=rule.id,
            org_id=org_id,
            event_type=event_type,
            task_id=task_id,
            payload_summary={k: str(v)[:200] for k, v in event_data.items() if v is not None},
        )
        db.add(trigger)

    if rules:
        await db.commit()
