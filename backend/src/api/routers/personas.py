"""Agent Personas router — org-scoped personality/capability templates."""
import io
import json
import uuid
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from src.core.database import get_db
from src.core.security import encrypt, decrypt
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.persona import Persona

router = APIRouter(prefix="/personas", tags=["personas"])


# Builtin personas are loaded from seeds/personas/builtin/*/persona.json
# via the seed loader. No hardcoded fallback list.

def _get_builtin_personas() -> list[dict]:
    """Load builtin personas from seed files."""
    from src.seeds.loader import get_all_personas
    loaded = get_all_personas()
    return [
        {
            "id": f"builtin:{p['key']}",
            "key": p["key"],
            "name": p.get("name", ""),
            "icon": p.get("icon"),
            "description": p.get("description"),
            "is_builtin": p.get("is_builtin", p.get("_source") == "builtin"),
            "soul": p.get("soul", {}),
            "system_prompt": p.get("system_prompt", ""),
            "default_skills": p.get("default_skills", []),
            "default_tools": p.get("default_tools", []),
            "default_mcps": p.get("default_mcps", []),
            "_md": p.get("_md"),
            "_dir": p.get("_dir"),
            "_source": p.get("_source"),
        }
        for p in loaded
    ]


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_org(user: User, db: AsyncSession) -> str:
    return await get_active_org_id(user, db)


async def _get_persona(persona_id: str, org_id: str, db: AsyncSession) -> Persona:
    r = await db.execute(select(Persona).where(Persona.id == persona_id, Persona.org_id == org_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")
    return p


# ─── Schemas ─────────────────────────────────────────────────────────────────

class PersonaCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    icon: str | None = None
    soul: dict = {}
    system_prompt: str | None = None
    default_skills: list[str] = []
    default_tools: list[str] = []
    default_mcps: list[dict] = []


class PersonaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    soul: dict | None = None
    system_prompt: str | None = None
    default_skills: list[str] | None = None
    default_tools: list[str] | None = None
    default_mcps: list[dict] | None = None


class PersonaResponse(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    icon: str | None
    soul: dict
    system_prompt: str | None
    default_skills: list
    default_tools: list
    default_mcps: list
    is_builtin: bool = False

    model_config = {"from_attributes": True}

    def model_post_init(self, __context: object) -> None:
        if self.soul is None: self.soul = {}
        if self.default_skills is None: self.default_skills = []
        if self.default_tools is None: self.default_tools = []
        if self.default_mcps is None: self.default_mcps = []


# ─── Builtin endpoint (must precede /{id}) ────────────────────────────────────

@router.get("/builtin")
async def list_builtin_personas(_: User = Depends(get_current_user)):
    return _get_builtin_personas()


@router.get("/builtin/{key}/files")
async def get_builtin_persona_files(key: str, _: User = Depends(get_current_user)):
    try:
        from src.seeds.loader import get_all_personas
        loaded = get_all_personas()
        p = next((x for x in loaded if x.get("key") == key), None)
        if not p:
            raise HTTPException(status_code=404, detail="Builtin persona not found")
        manifest = {
            "key": p["key"], "name": p.get("name", ""),
            "description": p.get("description", ""),
            "icon": p.get("icon"),
            "soul": p.get("soul", {}),
            "system_prompt": p.get("system_prompt", ""),
            "default_skills": p.get("default_skills", []),
            "default_tools": p.get("default_tools", []),
            "default_mcps": p.get("default_mcps", []),
        }
        files: dict[str, str] = {"persona.json": json.dumps(manifest, indent=2)}
        if "_md" in p:
            files["PERSONA.md"] = p["_md"]
        return {"files": files}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Builtin persona not found")


@router.get("/builtin/{key}/export")
async def export_builtin_persona(key: str, _: User = Depends(get_current_user)):
    try:
        from src.seeds.loader import get_all_personas
        loaded = get_all_personas()
        p = next((x for x in loaded if x.get("key") == key), None)
        if not p:
            raise HTTPException(status_code=404, detail="Builtin persona not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Builtin persona not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "key": p["key"], "name": p.get("name", ""),
            "description": p.get("description", ""),
            "icon": p.get("icon"),
            "soul": p.get("soul", {}),
            "system_prompt": p.get("system_prompt", ""),
            "default_skills": p.get("default_skills", []),
            "default_tools": p.get("default_tools", []),
            "default_mcps": p.get("default_mcps", []),
        }
        source = p.get("_source", "builtin")
        zf.writestr(f"persona/{source}/{key}/persona.json", json.dumps(manifest, indent=2))
        if "_md" in p:
            zf.writestr(f"persona/{source}/{key}/PERSONA.md", p["_md"])
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="persona_{key}.zip"'})


# ─── CRUD ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[PersonaResponse])
async def list_personas(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    result = await db.execute(select(Persona).where(Persona.org_id == org_id).order_by(Persona.name))
    return result.scalars().all()


@router.post("", response_model=PersonaResponse, status_code=201)
async def create_persona(
    req: PersonaCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    persona = Persona(
        id=str(uuid.uuid4()),
        org_id=org_id,
        key=req.key.lower().replace(" ", "_"),
        name=req.name,
        description=req.description,
        icon=req.icon,
        soul=req.soul,
        system_prompt=req.system_prompt,
        default_skills=req.default_skills,
        default_tools=req.default_tools,
        default_mcps=req.default_mcps,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    return persona


@router.patch("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: str,
    req: PersonaUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    persona = await _get_persona(persona_id, org_id, db)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(persona, field, value)
    await db.commit()
    await db.refresh(persona)
    return persona


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    persona = await _get_persona(persona_id, org_id, db)
    await db.delete(persona)
    await db.commit()


@router.get("/{persona_id}/export")
async def export_persona(
    persona_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    persona = await _get_persona(persona_id, org_id, db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "key": persona.key, "name": persona.name,
            "description": persona.description or "",
            "icon": persona.icon,
            "soul": persona.soul or {},
            "system_prompt": persona.system_prompt or "",
            "default_skills": persona.default_skills or [],
            "default_tools": persona.default_tools or [],
            "default_mcps": persona.default_mcps or [],
        }
        zf.writestr(f"persona/custom/{persona.key}/persona.json", json.dumps(manifest, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="persona_{persona.key}.zip"'})
