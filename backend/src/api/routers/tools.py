"""Tools catalog router."""
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
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.tool import Tool, TOOL_CATEGORIES

router = APIRouter(prefix="/tools", tags=["tools"])


# Builtin tools are loaded from seeds/tools/builtin/*/tool.json
# via the seed loader. No hardcoded fallback list.
# ─── Router ───────────────────────────────────────────────────────────────────

async def _get_org(user: User, db: AsyncSession) -> str:
    return await get_active_org_id(user, db)


async def _get_tool(tool_id: str, org_id: str, db: AsyncSession) -> Tool:
    r = await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == org_id))
    tool = r.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


class ToolCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    category: str = "custom"


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None


class ToolResponse(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    category: str
    is_builtin: bool = False
    env_vars: list[str] = []

    model_config = {"from_attributes": True}


# ─── /tools/builtin — must be before /{tool_id} ──────────────────────────────

def _builtin_tools_from_loader() -> list[dict]:
    """Return all filesystem tools (builtin + custom dirs)."""
    from src.seeds.loader import get_all_tools
    loaded = get_all_tools()
    result = []
    for t in loaded:
        files = {"TOOL.md": t["_md"]} if "_md" in t else {}
        result.append({
            "id": f"builtin:{t['key']}",
            "key": t["key"],
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "category": t.get("category", "custom"),
            "env_vars": t.get("env_vars", []),
            "is_builtin": t.get("is_builtin", t.get("_source") == "builtin"),
            "files": files,
        })
    return result


@router.get("/builtin")
async def list_builtin_tools(_: User = Depends(get_current_user)):
    return _builtin_tools_from_loader()


@router.get("/builtin/{key}/files")
async def get_builtin_tool_files(key: str, _: User = Depends(get_current_user)):
    from pathlib import Path
    try:
        from src.seeds.loader import get_all_tools
        loaded = get_all_tools()
        tool = next((t for t in loaded if t.get("key") == key), None)
        if not tool:
            raise HTTPException(status_code=404, detail="Builtin tool not found")
        files: dict = {}
        tool_dir = Path(tool.get("_dir", ""))
        if tool_dir.exists():
            for f in sorted(tool_dir.iterdir()):
                if f.is_file():
                    try:
                        files[f.name] = f.read_text(encoding="utf-8")
                    except Exception:
                        files[f.name] = ""
        elif "_md" in tool:
            files["TOOL.md"] = tool["_md"]
        return {"files": files}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Builtin tool not found")


@router.get("/builtin/{key}/export")
async def export_builtin_tool(key: str, _: User = Depends(get_current_user)):
    t = next((x for x in _builtin_tools_from_loader() if x["key"] == key), None)
    if not t:
        raise HTTPException(status_code=404, detail="Builtin tool not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "key": t["key"], "name": t["name"],
            "description": t.get("description", ""),
            "category": t.get("category", "custom"),
            "env_vars": t.get("env_vars", []),
        }
        zf.writestr(f"tool/builtin/{key}/tool.json", json.dumps(manifest, indent=2))
        for fname, content in (t.get("files") or {}).items():
            zf.writestr(f"tool/builtin/{key}/{fname}", content)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tool_{key}.zip"'})


# ─── CRUD ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ToolResponse])
async def list_tools(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    result = await db.execute(select(Tool).where(Tool.org_id == org_id).order_by(Tool.category, Tool.name))
    from src.core.permissions import filter_by_capability
    return await filter_by_capability(
        current_user, org_id, db, list(result.scalars().all()), "tool_keys", lambda t: t.key,
    )


@router.post("", response_model=ToolResponse, status_code=201)
async def create_tool(
    req: ToolCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.category not in TOOL_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Invalid category. Choose from: {sorted(TOOL_CATEGORIES)}")
    org_id = await _get_org(current_user, db)
    tool = Tool(
        id=str(uuid.uuid4()),
        org_id=org_id,
        key=req.key.lower().replace(" ", "_"),
        name=req.name,
        description=req.description,
        category=req.category,
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.patch("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: str,
    req: ToolUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    tool = await _get_tool(tool_id, org_id, db)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(tool, field, value)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    tool = await _get_tool(tool_id, org_id, db)
    await db.delete(tool)
    await db.commit()


@router.get("/{tool_id}/export")
async def export_tool(
    tool_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    tool = await _get_tool(tool_id, org_id, db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "key": tool.key, "name": tool.name,
            "description": tool.description or "",
            "category": tool.category, "env_vars": [],
        }
        zf.writestr(f"tool/custom/{tool.key}/tool.json", json.dumps(manifest, indent=2))
        for fname, content in (tool.files or {}).items():
            zf.writestr(f"tool/custom/{tool.key}/{fname}", content)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tool_{tool.key}.zip"'})


# ─── Tool file endpoints ──────────────────────────────────────────────────────

def _safe_path(path: str) -> str:
    norm = re.sub(r"[^\w.\-/]", "", path).lstrip("/")
    if ".." in norm.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    return norm


class FileWrite(BaseModel):
    content: str


@router.get("/{tool_id}/files")
async def list_tool_files(
    tool_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    tool = await _get_tool(tool_id, org_id, db)
    return {"files": tool.files or {}}


@router.put("/{tool_id}/files/{file_path:path}")
async def upsert_tool_file(
    tool_id: str,
    file_path: str,
    req: FileWrite,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    tool = await _get_tool(tool_id, org_id, db)
    path = _safe_path(file_path)
    files = dict(tool.files or {})
    files[path] = req.content
    tool.files = files
    await db.commit()
    return {"path": path, "content": req.content}


@router.delete("/{tool_id}/files/{file_path:path}", status_code=204)
async def delete_tool_file(
    tool_id: str,
    file_path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    tool = await _get_tool(tool_id, org_id, db)
    path = _safe_path(file_path)
    files = dict(tool.files or {})
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    del files[path]
    tool.files = files
    await db.commit()
