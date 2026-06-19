"""Agent system prompt builder."""
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.skill import Skill
from src.models.agent_memory import AgentMemory


async def get_agent_system_prompt(agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = r.scalar_one_or_none()
        if not agent:
            return None
        parts = []
        if agent.system_prompt:
            parts.append(agent.system_prompt)
        if agent.soul:
            soul = agent.soul
            if soul.get("personality"):
                parts.append(f"Personality: {soul['personality']}")
            if soul.get("expertise"):
                expertise = soul["expertise"]
                if isinstance(expertise, list):
                    parts.append(f"Expertise: {', '.join(expertise)}")
            if soul.get("communication_style"):
                parts.append(f"Communication style: {soul['communication_style']}")

        skill_keys = [s for s in (agent.skills or []) if isinstance(s, str)]
        if skill_keys:
            r2 = await db.execute(
                select(Skill).where(
                    Skill.org_id == agent.org_id,
                    Skill.key.in_(skill_keys),
                )
            )
            skills = r2.scalars().all()
            for skill in skills:
                skill_doc = (skill.files or {}).get("SKILL.md")
                if skill_doc:
                    parts.append(f"---\n## Skill: {skill.name}\n\n{skill_doc}")

        if agent.env_vars:
            env_lines = ["## Your Environment Variables", ""]
            for k, v in agent.env_vars.items():
                env_lines.append(f"  {k} = {v}")
            parts.append("\n".join(env_lines))

        mem_result = await db.execute(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent.id)
            .order_by(AgentMemory.priority.desc(), AgentMemory.created_at)
        )
        memories = mem_result.scalars().all()
        if memories:
            mem_lines = ["## Memory"]
            for m in memories:
                tag_str = f" [{', '.join(m.tags)}]" if m.tags else ""
                mem_lines.append(f"- [{m.type}]{tag_str} {m.content}")
            parts.append("\n".join(mem_lines))

        return "\n\n".join(parts) if parts else None
