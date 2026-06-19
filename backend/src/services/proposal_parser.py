"""Parse <proposal> blocks from agent responses and execute or queue them."""
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.core.config import get_settings
from src.models.agent_proposal import AgentProposal, PROPOSAL_TYPES
from src.models.chat import Chat
from src.models.agent import Agent

logger = logging.getLogger(__name__)

_PROPOSAL_RE = re.compile(
    r"<proposal>(.*?)</proposal>",
    re.DOTALL | re.IGNORECASE,
)


def strip_proposals(text: str) -> str:
    """Remove all <proposal> blocks from text before displaying to user."""
    return _PROPOSAL_RE.sub("", text).strip()


def _parse_proposal_block(raw: str) -> dict | None:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except json.JSONDecodeError:
        return None


async def _auto_execute(proposal: AgentProposal, db) -> dict | None:
    """Execute a proposal immediately and return the result."""
    ptype = proposal.proposal_type
    payload = proposal.payload or {}
    chat_id = proposal.chat_id

    try:
        if ptype == "create_issue":
            from src.seeds.tools.builtin.issue_manage.executor import execute as _issue_exec
            result = await _issue_exec(
                {"action": "create", **payload},
                chat_id=chat_id,
                agent_id=proposal.agent_id,
                agent_name=proposal.agent_name,
            )
            return result

        elif ptype == "create_task":
            from src.services.agent_tools.tool_executor import _run_single_tool
            result = await _run_single_tool(
                "task_create", payload,
                chat_id=chat_id,
                agent_id=proposal.agent_id,
                agent_name=proposal.agent_name,
            )
            return result

        elif ptype == "trigger_pipeline":
            from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_exec
            result = await _gl_exec(
                {"action": "trigger_pipeline", **payload},
                chat_id=chat_id,
                agent_id=proposal.agent_id,
                agent_name=proposal.agent_name,
            )
            return result

        elif ptype == "spawn_agent":
            from src.seeds.tools.builtin.platform_create_agent.executor import execute as _spawn_exec
            result = await _spawn_exec(
                payload,
                chat_id=chat_id,
                agent_id=proposal.agent_id,
                agent_name=proposal.agent_name,
            )
            return result

        else:
            # custom or unhandled — mark as auto_approved but no execution
            return {"status": "queued", "note": f"proposal_type '{ptype}' requires manual execution"}

    except Exception as exc:
        logger.warning(f"[proposals] auto-execute failed for {proposal.id}: {exc}")
        return {"error": str(exc)}


async def process_proposals(
    response_text: str,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
    org_id: str,
) -> int:
    """Extract <proposal> blocks, persist them, and auto-approve high-confidence ones.

    Returns the number of proposals found.
    """
    matches = _PROPOSAL_RE.findall(response_text)
    if not matches:
        return 0

    settings = get_settings()
    threshold = settings.proposal_auto_approve_confidence
    created = []

    async with AsyncSessionLocal() as db:
        for raw in matches:
            data = _parse_proposal_block(raw)
            if not data:
                logger.warning(f"[proposals] could not parse proposal block: {raw[:200]}")
                continue

            ptype = data.get("type", "custom")
            if ptype not in PROPOSAL_TYPES:
                ptype = "custom"

            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            proposal = AgentProposal(
                id=str(uuid.uuid4()),
                org_id=org_id,
                chat_id=chat_id,
                agent_id=agent_id,
                agent_name=agent_name,
                proposal_type=ptype,
                title=str(data.get("title", ptype))[:500],
                rationale=data.get("rationale") or data.get("description"),
                payload={k: v for k, v in data.items() if k not in ("type", "confidence", "title", "rationale", "description")},
                confidence=confidence,
                status="pending",
            )
            db.add(proposal)
            await db.flush()
            created.append(proposal)

        await db.commit()

    # Auto-approve and execute high-confidence proposals outside the main DB session
    for proposal in created:
        if proposal.confidence >= threshold:
            result = await _auto_execute(proposal, None)
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(AgentProposal).where(AgentProposal.id == proposal.id))
                p = r.scalar_one_or_none()
                if p:
                    p.status = "auto_approved"
                    p.reviewed_at = datetime.now(timezone.utc)
                    p.execution_result = result
                    await db.commit()
            logger.info(f"[proposals] auto-approved '{proposal.title}' (confidence={proposal.confidence:.2f})")
        else:
            # Notify user via pubsub so UI can surface the pending proposal
            try:
                from src.core.pubsub import broadcast as _broadcast
                await _broadcast(chat_id, {
                    "type": "proposal_pending",
                    "proposal": {
                        "id": proposal.id,
                        "proposal_type": proposal.proposal_type,
                        "title": proposal.title,
                        "rationale": proposal.rationale,
                        "confidence": proposal.confidence,
                        "agent_name": proposal.agent_name,
                    },
                })
            except Exception:
                pass
            logger.info(f"[proposals] queued for review: '{proposal.title}' (confidence={proposal.confidence:.2f})")

    return len(created)
