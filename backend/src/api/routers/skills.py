"""Skills catalog router."""
import io
import json
import uuid
import re
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.skill import Skill, SKILL_CATEGORIES

router = APIRouter(prefix="/skills", tags=["skills"])


async def _get_org(user: User, db: AsyncSession) -> str:
    return await get_active_org_id(user, db)


class SkillCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    category: str = "custom"


class SkillResponse(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    category: str
    is_builtin: bool

    model_config = {"from_attributes": True}


@router.get("/builtin")
async def list_builtin(_=Depends(get_current_user)):
    from src.seeds.loader import get_all_skills
    loaded = get_all_skills()
    return [
        {
            "key": s["key"],
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "category": s.get("category", "custom"),
            "is_builtin": s.get("is_builtin", s.get("_source") == "builtin"),
            "files": {"SKILL.md": s["_md"]} if "_md" in s else {},
        }
        for s in loaded
    ]


@router.get("/builtin/{skill_key}/files")
async def get_builtin_skill_files(skill_key: str, _=Depends(get_current_user)):
    from pathlib import Path
    try:
        from src.seeds.loader import get_all_skills
        loaded = get_all_skills()
        skill = next((s for s in loaded if s.get("key") == skill_key), None)
        if not skill:
            raise HTTPException(status_code=404, detail="Builtin skill not found")
        files: dict = {}
        skill_dir = Path(skill.get("_dir", ""))
        if skill_dir.exists():
            for f in sorted(skill_dir.iterdir()):
                if f.is_file():
                    try:
                        files[f.name] = f.read_text(encoding="utf-8")
                    except Exception:
                        files[f.name] = ""
        elif "_md" in skill:
            files["SKILL.md"] = skill["_md"]
        return {"files": files}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Builtin skill not found")


@router.get("/builtin/{skill_key}/export")
async def export_builtin_skill(skill_key: str, _=Depends(get_current_user)):
    try:
        from src.seeds.loader import get_all_skills
        loaded = get_all_skills()
        skill = next((s for s in loaded if s.get("key") == skill_key), None)
        if not skill:
            raise HTTPException(status_code=404, detail="Builtin skill not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Builtin skill not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "key": skill["key"], "name": skill.get("name", ""),
            "description": skill.get("description", ""),
            "category": skill.get("category", "custom"),
        }
        is_blt = skill.get("is_builtin", skill.get("_source") == "builtin")
        source = "builtin" if is_blt else "custom"
        zf.writestr(f"skill/{source}/{skill_key}/skill.json", json.dumps(manifest, indent=2))
        if "_md" in skill:
            zf.writestr(f"skill/{source}/{skill_key}/SKILL.md", skill["_md"])
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="skill_{skill_key}.zip"'})


@router.get("", response_model=list[SkillResponse])
async def list_skills(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    result = await db.execute(select(Skill).where(Skill.org_id == org_id).order_by(Skill.category, Skill.name))
    return result.scalars().all()


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(
    req: SkillCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.category not in SKILL_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Invalid category. Choose from: {sorted(SKILL_CATEGORIES)}")
    org_id = await _get_org(current_user, db)
    skill = Skill(
        id=str(uuid.uuid4()),
        org_id=org_id,
        key=req.key.lower().replace(" ", "_"),
        name=req.name,
        description=req.description,
        category=req.category,
        is_builtin=False,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    r = await db.execute(select(Skill).where(Skill.id == skill_id, Skill.org_id == org_id))
    skill = r.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.is_builtin:
        raise HTTPException(status_code=400, detail="Cannot delete built-in skills")
    await db.delete(skill)
    await db.commit()


@router.get("/{skill_id}/export")
async def export_skill(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    r = await db.execute(select(Skill).where(Skill.id == skill_id, Skill.org_id == org_id))
    skill = r.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "key": skill.key, "name": skill.name,
            "description": skill.description or "",
            "category": skill.category,
        }
        zf.writestr(f"skill/custom/{skill.key}/skill.json", json.dumps(manifest, indent=2))
        for fname, content in (skill.files or {}).items():
            zf.writestr(f"skill/custom/{skill.key}/{fname}", content)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="skill_{skill.key}.zip"'})


# ─── Skill file endpoints ────────────────────────────────────────

def _safe_path(path: str) -> str:
    """Normalize path and reject traversal attempts."""
    norm = re.sub(r"[^\w.\-/]", "", path).lstrip("/")
    if ".." in norm.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    return norm


async def _get_custom_skill(skill_id: str, org_id: str, db: AsyncSession) -> Skill:
    r = await db.execute(select(Skill).where(Skill.id == skill_id, Skill.org_id == org_id))
    skill = r.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.is_builtin:
        raise HTTPException(status_code=400, detail="Built-in skills cannot have custom files")
    return skill


class FileTree(BaseModel):
    files: dict[str, str]  # path → content


class FileWrite(BaseModel):
    content: str


@router.get("/{skill_id}/files", response_model=FileTree)
async def list_skill_files(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    skill = await _get_custom_skill(skill_id, org_id, db)
    return {"files": skill.files or {}}


@router.get("/{skill_id}/files/{file_path:path}", response_model=dict)
async def get_skill_file(
    skill_id: str,
    file_path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    skill = await _get_custom_skill(skill_id, org_id, db)
    path = _safe_path(file_path)
    files = skill.files or {}
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": path, "content": files[path]}


@router.put("/{skill_id}/files/{file_path:path}", response_model=dict)
async def upsert_skill_file(
    skill_id: str,
    file_path: str,
    req: FileWrite,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    skill = await _get_custom_skill(skill_id, org_id, db)
    path = _safe_path(file_path)
    files = dict(skill.files or {})
    files[path] = req.content
    skill.files = files
    await db.commit()
    await db.refresh(skill)
    return {"path": path, "content": req.content}


@router.delete("/{skill_id}/files/{file_path:path}", status_code=204)
async def delete_skill_file(
    skill_id: str,
    file_path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    skill = await _get_custom_skill(skill_id, org_id, db)
    path = _safe_path(file_path)
    files = dict(skill.files or {})
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    del files[path]
    skill.files = files
    await db.commit()
