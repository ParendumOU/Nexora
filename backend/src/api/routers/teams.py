"""Teams router — spawn a full agent team from persona templates in one request."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.services.team_spawner import MemberSpec, spawn_team

router = APIRouter(prefix="/teams", tags=["teams"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class MemberSpecRequest(BaseModel):
    persona_key: str
    count: int = Field(default=1, ge=1, le=20)
    name_prefix: str | None = None
    overrides: dict = {}


class TeamSpawnRequest(BaseModel):
    team_name: str | None = None
    members: list[MemberSpecRequest] = Field(min_length=1)


class AgentCreated(BaseModel):
    id: str
    name: str
    persona_key: str
    agent_type: str
    skills: list
    tools: list


class TeamSpawnResponse(BaseModel):
    team_name: str | None
    agents: list[AgentCreated]
    total: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/personas")
async def list_spawnable_personas(
    current_user: User = Depends(get_current_user),
):
    """Return available persona keys that can be used in a team spawn request."""
    from src.seeds.loader import get_all_personas
    return [
        {
            "key": p["key"],
            "name": p.get("name", ""),
            "icon": p.get("icon"),
            "description": p.get("description"),
            "default_skills": p.get("default_skills", []),
        }
        for p in get_all_personas()
    ]


@router.post("/spawn", response_model=TeamSpawnResponse, status_code=201)
async def spawn_team_endpoint(
    req: TeamSpawnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple agents at once using persona templates.

    Example — spawn 3 developers, 1 QA, and 1 DevOps engineer:

        {
          "team_name": "Feature Team Alpha",
          "members": [
            {"persona_key": "developer", "count": 3},
            {"persona_key": "qa_engineer", "count": 1},
            {"persona_key": "devops", "count": 1}
          ]
        }
    """
    from src.seeds.loader import get_all_personas
    valid_keys = {p["key"] for p in get_all_personas()}
    unknown = [m.persona_key for m in req.members if m.persona_key not in valid_keys]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown persona key(s): {unknown}. Valid keys: {sorted(valid_keys)}",
        )

    org_id = await get_active_org_id(current_user, db)
    specs = [
        MemberSpec(
            persona_key=m.persona_key,
            count=m.count,
            name_prefix=m.name_prefix,
            overrides=m.overrides,
        )
        for m in req.members
    ]

    result = await spawn_team(org_id=org_id, members=specs, team_name=req.team_name, db=db)

    return TeamSpawnResponse(
        team_name=result.team_name,
        agents=[AgentCreated(**a) for a in result.agents],
        total=result.total,
    )
