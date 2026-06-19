"""Team spawner — creates multiple agents from persona templates in one call."""
import uuid
import logging
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.agent import Agent
from src.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass
class MemberSpec:
    persona_key: str
    count: int = 1
    name_prefix: str | None = None
    overrides: dict = field(default_factory=dict)


@dataclass
class SpawnResult:
    agents: list[dict]
    team_name: str | None

    @property
    def total(self) -> int:
        return len(self.agents)


def _resolve_persona(key: str) -> dict | None:
    """Return persona seed data for key, or None if not found."""
    from src.seeds.loader import get_all_personas
    for p in get_all_personas():
        if p.get("key") == key:
            return p
    return None


def _agent_name(persona_name: str, index: int, count: int, prefix: str | None) -> str:
    base = f"{prefix} {persona_name}" if prefix else persona_name
    if count == 1:
        return base
    return f"{base} {index}"


def _build_agent(
    org_id: str,
    persona: dict,
    spec: MemberSpec,
    index: int,
) -> Agent:
    overrides = spec.overrides or {}
    soul = {**persona.get("soul", {}), **overrides.get("soul", {})}
    skills = overrides.get("skills") or persona.get("default_skills", [])
    tools = overrides.get("tools") or persona.get("default_tools", [])
    mcps = overrides.get("mcps") or persona.get("default_mcps", [])

    return Agent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=_agent_name(persona["name"], index, spec.count, spec.name_prefix),
        agent_type=overrides.get("agent_type") or persona.get("key", "custom"),
        description=overrides.get("description") or persona.get("description"),
        soul=soul,
        system_prompt=overrides.get("system_prompt") or persona.get("system_prompt"),
        skills=skills,
        tools=tools,
        mcps=mcps,
        env_vars=overrides.get("env_vars", {}),
        temperature=overrides.get("temperature", 0.3),
        max_tokens=str(overrides.get("max_tokens", 8192)),
        is_active=True,
    )


async def spawn_team(
    org_id: str,
    members: list[MemberSpec],
    team_name: str | None = None,
    db: AsyncSession | None = None,
) -> SpawnResult:
    """Create all agents defined by *members* under *org_id*.

    Accepts an optional open session; otherwise opens its own.
    """
    created: list[dict] = []
    errors: list[str] = []

    # Per-license agent quota (no-op in OSS): cap the team to remaining slots.
    from src.services.billing_limits import agent_slots_remaining
    remaining = await agent_slots_remaining(org_id)  # None = unlimited

    async def _run(session: AsyncSession) -> None:
        nonlocal remaining
        for spec in members:
            persona = _resolve_persona(spec.persona_key)
            if not persona:
                errors.append(f"Unknown persona key: {spec.persona_key!r}")
                logger.warning(f"[team_spawn] unknown persona {spec.persona_key!r} — skipping")
                continue

            for i in range(1, spec.count + 1):
                if remaining is not None and remaining <= 0:
                    errors.append("Agent limit reached for your plan — remaining team members not created. Upgrade your license.")
                    logger.warning("[team_spawn] agent limit reached for org %s — stopping", org_id)
                    await session.commit()
                    return
                agent = _build_agent(org_id, persona, spec, i)
                if remaining is not None:
                    remaining -= 1
                session.add(agent)
                await session.flush()
                await session.refresh(agent)
                created.append({
                    "id": agent.id,
                    "name": agent.name,
                    "persona_key": spec.persona_key,
                    "agent_type": agent.agent_type,
                    "skills": agent.skills or [],
                    "tools": agent.tools or [],
                })
                logger.info(f"[team_spawn] created agent {agent.name!r} ({agent.id})")

        await session.commit()

    if db is not None:
        await _run(db)
    else:
        async with AsyncSessionLocal() as session:
            await _run(session)

    return SpawnResult(agents=created, team_name=team_name)
