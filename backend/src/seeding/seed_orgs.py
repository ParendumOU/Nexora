"""Idempotent seed: provisions seeded agents (builtin + custom) and skills for every org from seeds/ filesystem."""
import uuid
import logging
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import AsyncSessionLocal
from src.models.org import Organization
from src.models.skill import Skill
from src.models.agent import Agent

logger = logging.getLogger(__name__)


async def seed_org(org_id: str, db: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError
    from src.seeds.loader import get_all_skills, get_all_agents

    # ── Skills (both builtin and custom) ──────────────────────────────
    # We re-sync the file content on every seed run so SKILL.md edits in
    # the source tree propagate to live agents without manual DB surgery.
    for skill_data in get_all_skills():
        key = skill_data.get("key", "")
        if not key:
            continue
        is_builtin = skill_data.get("_source") == "builtin"
        r = await db.execute(
            select(Skill).where(Skill.org_id == org_id, Skill.key == key)
        )
        all_matching = r.scalars().all()
        existing = all_matching[0] if all_matching else None
        dup_ids = [dup.id for dup in all_matching[1:]]
        if dup_ids:
            await db.execute(delete(Skill).where(Skill.id.in_(dup_ids)))
        files = {"SKILL.md": skill_data.get("_md", "")}
        if existing:
            existing.files = files
            existing.description = skill_data.get("description", existing.description)
            existing.name = skill_data.get("name", existing.name)
            existing.category = skill_data.get("category", existing.category)
            existing.is_builtin = is_builtin
        else:
            db.add(Skill(
                id=str(uuid.uuid4()),
                org_id=org_id,
                key=key,
                name=skill_data.get("name", key),
                description=skill_data.get("description", ""),
                category=skill_data.get("category", "custom"),
                is_builtin=is_builtin,
                files=files,
            ))

    # ── Seeded agents (builtin + custom) ──────────────────────────────
    for agent_data in get_all_agents():
        name = agent_data.get("name", "")
        if not name:
            continue
        is_builtin = agent_data.get("_source") == "builtin"
        r = await db.execute(
            select(Agent)
            .where(Agent.org_id == org_id, Agent.name == name, Agent.is_active == True)
            .order_by(Agent.is_builtin.desc())
        )
        all_existing = r.scalars().all()
        if not all_existing:
            db.add(Agent(
                id=str(uuid.uuid4()),
                org_id=org_id,
                name=name,
                agent_type=agent_data.get("agent_type", "custom"),
                description=agent_data.get("description", ""),
                system_prompt=agent_data.get("system_prompt", ""),
                skills=agent_data.get("skills", []),
                tools=agent_data.get("tools", []),
                soul=agent_data.get("soul", {}),
                temperature=agent_data.get("temperature", 0.3),
                max_tokens=int(agent_data["max_tokens"]) if agent_data.get("max_tokens") else None,
                is_active=True,
                is_builtin=is_builtin,
            ))
        else:
            kept = all_existing[0]
            kept.is_builtin = is_builtin
            if agent_data.get("system_prompt"):
                kept.system_prompt = agent_data["system_prompt"]
            if agent_data.get("tools") is not None:
                kept.tools = agent_data["tools"]
            if agent_data.get("skills") is not None:
                kept.skills = agent_data["skills"]
            for extra in all_existing[1:]:
                extra.is_active = False

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.debug(f"[seed] concurrent insert race for org {org_id} — safely ignored")


async def seed_all() -> None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Organization))
        orgs = r.scalars().all()
        for org in orgs:
            try:
                await seed_org(org.id, db)
                logger.info(f"[seed] agents+skills seeded for org {org.id}")
            except Exception as exc:
                logger.warning(f"[seed] failed for org {org.id}: {exc}")
