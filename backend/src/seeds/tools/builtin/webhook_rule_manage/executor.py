"""webhook_rule_manage — agent tool for managing GitLab/GitHub webhook trigger rules."""
import uuid
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.webhook_rule import WebhookRule, WebhookRuleTrigger
from src.models.agent import Agent
from src.models.chat import Chat


async def _resolve_org(agent_id: str | None, chat_id: str) -> str | None:
    # Robust chain (agent → chat parent walk → root user org).
    from src.services.org_resolve import resolve_chat_org
    async with AsyncSessionLocal() as db:
        return await resolve_chat_org(db, chat_id, agent_id)


def _rule_dict(r: WebhookRule) -> dict:
    return {
        "id": r.id,
        "source": r.source,
        "event_type": r.event_type,
        "filter_json": r.filter_json,
        "agent_id": r.agent_id,
        "task_title_template": r.task_title_template,
        "task_description_template": r.task_description_template,
        "project_id": r.project_id,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat(),
    }


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    action = (args.get("action") or "").strip().lower()
    valid = ("list", "create", "get", "update", "delete", "list_triggers")
    if action not in valid:
        return {"error": f"action must be one of: {', '.join(valid)}"}

    org_id = await _resolve_org(agent_id, chat_id)
    if not org_id:
        return {"error": "Could not resolve org_id"}

    async with AsyncSessionLocal() as db:

        if action == "list":
            q = select(WebhookRule).where(WebhookRule.org_id == org_id)
            if args.get("source"):
                q = q.where(WebhookRule.source == args["source"])
            if args.get("event_type"):
                q = q.where(WebhookRule.event_type == args["event_type"])
            if args.get("active_only"):
                q = q.where(WebhookRule.is_active == True)  # noqa: E712
            result = await db.execute(q.order_by(WebhookRule.created_at.desc()))
            rules = result.scalars().all()
            return {"data": {"rules": [_rule_dict(r) for r in rules], "count": len(rules)}}

        if action == "get":
            rule_id = args.get("rule_id")
            if not rule_id:
                return {"error": "rule_id is required for get"}
            r = await db.execute(
                select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
            )
            rule = r.scalar_one_or_none()
            if not rule:
                return {"error": f"Rule {rule_id} not found"}
            return {"data": _rule_dict(rule)}

        if action == "create":
            source = args.get("source")
            event_type = args.get("event_type")
            target_agent_id = args.get("agent_id")
            title_template = args.get("task_title_template")
            if not all([source, event_type, target_agent_id, title_template]):
                return {"error": "source, event_type, agent_id, and task_title_template are required"}
            # Verify target agent belongs to this org
            r = await db.execute(
                select(Agent).where(Agent.id == target_agent_id, Agent.org_id == org_id)
            )
            if not r.scalar_one_or_none():
                return {"error": f"Agent {target_agent_id} not found in this org"}
            rule = WebhookRule(
                id=str(uuid.uuid4()),
                org_id=org_id,
                source=source,
                event_type=event_type,
                filter_json=args.get("filter_json"),
                agent_id=target_agent_id,
                task_title_template=title_template,
                task_description_template=args.get("task_description_template"),
                webhook_secret=args.get("webhook_secret"),
                project_id=args.get("project_id"),
                is_active=args.get("is_active", True),
            )
            db.add(rule)
            await db.commit()
            await db.refresh(rule)
            return {"data": _rule_dict(rule)}

        if action == "update":
            rule_id = args.get("rule_id")
            if not rule_id:
                return {"error": "rule_id is required for update"}
            r = await db.execute(
                select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
            )
            rule = r.scalar_one_or_none()
            if not rule:
                return {"error": f"Rule {rule_id} not found"}
            updatable = (
                "source", "event_type", "filter_json", "agent_id",
                "task_title_template", "task_description_template",
                "webhook_secret", "project_id", "is_active",
            )
            for field in updatable:
                if field in args:
                    setattr(rule, field, args[field])
            await db.commit()
            await db.refresh(rule)
            return {"data": _rule_dict(rule)}

        if action == "delete":
            rule_id = args.get("rule_id")
            if not rule_id:
                return {"error": "rule_id is required for delete"}
            r = await db.execute(
                select(WebhookRule).where(WebhookRule.id == rule_id, WebhookRule.org_id == org_id)
            )
            rule = r.scalar_one_or_none()
            if not rule:
                return {"error": f"Rule {rule_id} not found"}
            await db.delete(rule)
            await db.commit()
            return {"data": {"deleted": rule_id}}

        if action == "list_triggers":
            rule_id = args.get("rule_id")
            q = (
                select(WebhookRuleTrigger)
                .where(WebhookRuleTrigger.org_id == org_id)
                .order_by(WebhookRuleTrigger.created_at.desc())
            )
            if rule_id:
                q = q.where(WebhookRuleTrigger.rule_id == rule_id)
            limit = min(int(args.get("limit", 50)), 200)
            q = q.limit(limit)
            result = await db.execute(q)
            triggers = result.scalars().all()
            return {"data": {
                "triggers": [
                    {
                        "id": t.id, "rule_id": t.rule_id, "event_type": t.event_type,
                        "task_id": t.task_id, "payload_summary": t.payload_summary,
                        "created_at": t.created_at.isoformat(),
                    }
                    for t in triggers
                ],
                "count": len(triggers),
            }}

    return {"error": "Unhandled action"}
