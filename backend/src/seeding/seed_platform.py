"""Idempotent seed: creates the built-in system user, org, and Infrastructure Manager agent."""
import uuid
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import AsyncSessionLocal
from src.core.security import hash_password
from src.models.user import User
from src.models.org import Organization, OrgMember, OrgRole
from src.models.agent import Agent
from pathlib import Path
from src.models.skill import Skill

_PM_SKILL_MD_PATH = Path(__file__).parent.parent / "seeds" / "skills" / "builtin" / "platform_management" / "SKILL.md"
PLATFORM_SKILL_MD = _PM_SKILL_MD_PATH.read_text(encoding="utf-8") if _PM_SKILL_MD_PATH.exists() else ""

_SM_AGENT_MD_PATH = Path(__file__).parent.parent / "seeds" / "agents" / "builtin" / "scrum_master" / "AGENT.md"
SCRUM_MASTER_PROMPT = _SM_AGENT_MD_PATH.read_text(encoding="utf-8") if _SM_AGENT_MD_PATH.exists() else ""

logger = logging.getLogger(__name__)

# Fixed UUIDs — never change these; idempotency depends on them.
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"
SYSTEM_ORG_ID = "00000000-0000-0000-0000-000000000010"
INFRA_AGENT_ID = "00000000-0000-0000-0000-000000000100"
SCRUM_MASTER_ID = "00000000-0000-0000-0000-000000000200"
PLATFORM_SKILL_ID = "00000000-0000-0000-0000-000000001000"

from src.seeds.loader import get_prompt as _get_prompt
_INFRA_SYSTEM_PROMPT = _get_prompt("infra_system_prompt")


async def seed_system() -> None:
    """Create the built-in system user, Nexora Platform org, and Infrastructure Manager agent."""
    async with AsyncSessionLocal() as db:
        # ── System user ───────────────────────────────────────────────────────
        r = await db.execute(select(User).where(User.id == SYSTEM_USER_ID))
        system_user = r.scalar_one_or_none()
        if not system_user:
            system_user = User(
                id=SYSTEM_USER_ID,
                email="system@nexora.internal",
                full_name="Nexora System",
                hashed_password=hash_password(str(uuid.uuid4())),  # random, not for login
                is_active=True,
                is_superuser=True,
            )
            db.add(system_user)
            await db.flush()
            logger.info("[seed_platform] created system user")

        # ── System org ────────────────────────────────────────────────────────
        r = await db.execute(select(Organization).where(Organization.id == SYSTEM_ORG_ID))
        system_org = r.scalar_one_or_none()
        if not system_org:
            db.add(Organization(
                id=SYSTEM_ORG_ID,
                name="Nexora Platform",
                slug="nexora-platform",
                owner_id=SYSTEM_USER_ID,
                plan="system",
                icon="⚙️",
                color="#6366f1",
                is_personal=True,
            ))
            await db.flush()

            db.add(OrgMember(
                id=str(uuid.uuid4()),
                org_id=SYSTEM_ORG_ID,
                user_id=SYSTEM_USER_ID,
                role=OrgRole.owner,
            ))
            system_user.active_org_id = SYSTEM_ORG_ID
            await db.flush()
            logger.info("[seed_platform] created Nexora Platform org")

        # ── Platform management skill ─────────────────────────────────────────
        r = await db.execute(select(Skill).where(Skill.id == PLATFORM_SKILL_ID))
        existing_skill = r.scalar_one_or_none()
        if existing_skill:
            existing_skill.files = {"SKILL.md": PLATFORM_SKILL_MD}
        else:
            db.add(Skill(
                id=PLATFORM_SKILL_ID,
                org_id=SYSTEM_ORG_ID,
                key="platform_management",
                name="Platform Management",
                description=(
                    "Operational control over Nexora platform services: "
                    "audit source files, apply edits, view logs, restart containers"
                ),
                category="custom",
                is_builtin=True,
                files={"SKILL.md": PLATFORM_SKILL_MD},
            ))
            logger.info("[seed_platform] created platform_management skill")

        # ── Infrastructure Manager agent ──────────────────────────────────────
        r = await db.execute(select(Agent).where(Agent.id == INFRA_AGENT_ID))
        existing_agent = r.scalar_one_or_none()
        if existing_agent:
            existing_agent.system_prompt = _INFRA_SYSTEM_PROMPT
            existing_agent.skills = ["platform_management", "schedule_manage"]
            existing_agent.tools = ["shell_run", "file_read", "file_write", "docker_ps", "docker_logs"]
        else:
            db.add(Agent(
                id=INFRA_AGENT_ID,
                org_id=SYSTEM_ORG_ID,
                name="Infrastructure Manager",
                agent_type="devops",
                description=(
                    "Built-in DevOps agent with full access to platform source code and Docker daemon. "
                    "Can audit, edit, and restart backend and frontend services."
                ),
                system_prompt=_INFRA_SYSTEM_PROMPT,
                skills=["platform_management", "schedule_manage"],
                tools=["shell_run", "file_read", "file_write", "docker_ps", "docker_logs"],
                soul={
                    "personality": "precise, safety-conscious, infrastructure-focused",
                    "expertise": ["DevOps", "Docker", "FastAPI", "Next.js", "platform operations"],
                    "communication_style": "clear, warns before destructive actions, confirms before restarts",
                },
                temperature=0.1,
                is_active=True,
            ))
            logger.info("[seed_platform] created Infrastructure Manager agent")

        # ── Scrum Master agent ────────────────────────────────────────────────
        r = await db.execute(select(Agent).where(Agent.id == SCRUM_MASTER_ID))
        existing_sm = r.scalar_one_or_none()
        if existing_sm:
            existing_sm.system_prompt = SCRUM_MASTER_PROMPT
            existing_sm.skills = ["schedule_manage"]
            existing_sm.tools = [
                "agent_broadcast", "agent_read_inbox", "agent_notify",
                "list_available_agents", "memory_manage", "chat_notes",
                "task_create", "task_update", "send_message_to_agent",
            ]
        else:
            db.add(Agent(
                id=SCRUM_MASTER_ID,
                org_id=SYSTEM_ORG_ID,
                name="Scrum Master",
                agent_type="coordinator",
                description=(
                    "Built-in facilitator agent that runs daily standups, sprint planning, "
                    "and blocker resolution for all active agents in the org."
                ),
                system_prompt=SCRUM_MASTER_PROMPT,
                skills=["schedule_manage"],
                tools=[
                    "agent_broadcast", "agent_read_inbox", "agent_notify",
                    "list_available_agents", "memory_manage", "chat_notes",
                    "task_create", "task_update", "send_message_to_agent",
                ],
                soul={
                    "personality": "organized, concise, empathetic, neutral",
                    "expertise": ["agile facilitation", "team coordination", "blocker resolution", "async communication"],
                    "communication_style": "structured, bullet-pointed, time-boxed",
                    "subscribed_events": ["agent_blocked"],
                },
                temperature=0.2,
                max_tokens=8192,
                is_active=True,
            ))
            logger.info("[seed_platform] created Scrum Master agent")

        await db.commit()
