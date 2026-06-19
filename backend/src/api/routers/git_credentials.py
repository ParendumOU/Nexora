"""Git credentials — store PATs for GitHub/GitLab access."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.core.security import encrypt, decrypt
from src.models.user import User
from src.models.git_credential import GitCredential
from fastapi import Query
from src.services.git_repo_browser import fetch_tree_for_credential, fetch_root_nodes_for_credential, fetch_node_children_for_credential

router = APIRouter(prefix="/git-credentials", tags=["git"])


class CredentialCreate(BaseModel):
    name: str
    provider: str       # "github" | "gitlab"
    token: str
    color: str = "#6366f1"
    base_url: str | None = None


class CredentialUpdate(BaseModel):
    name: str | None = None
    token: str | None = None
    color: str | None = None
    base_url: str | None = None


def _serialize(c: GitCredential) -> dict:
    try:
        plaintext = decrypt(c.token)
        hint = f"••••{plaintext[-4:]}" if len(plaintext) >= 4 else "••••"
    except Exception:
        hint = "••••"
    return {
        "id": c.id,
        "name": c.name,
        "provider": c.provider,
        "color": c.color,
        "base_url": c.base_url,
        "token_hint": hint,
        "created_at": c.created_at.isoformat(),
    }


@router.get("", response_model=list[dict])
async def list_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(GitCredential).where(GitCredential.org_id == org_id).order_by(GitCredential.created_at))
    return [_serialize(c) for c in r.scalars().all()]


@router.post("", response_model=dict, status_code=201)
async def create_credential(
    req: CredentialCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    cred = GitCredential(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        provider=req.provider,
        token=encrypt(req.token),
        color=req.color,
        base_url=req.base_url or None,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return _serialize(cred)


@router.patch("/{cred_id}", response_model=dict)
async def update_credential(
    cred_id: str,
    req: CredentialUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(GitCredential).where(GitCredential.id == cred_id, GitCredential.org_id == org_id))
    cred = r.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    if req.name is not None:
        cred.name = req.name
    if req.token is not None:
        cred.token = encrypt(req.token)
    if req.color is not None:
        cred.color = req.color
    if req.base_url is not None:
        cred.base_url = req.base_url or None
    await db.commit()
    await db.refresh(cred)
    return _serialize(cred)


@router.get("/{cred_id}/repos/expand", response_model=dict)
async def expand_repo_node(
    cred_id: str,
    node_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lazy tree expansion.
    No node_id → returns root group stubs (no repos loaded).
    node_id → returns {repos, subgroups} for that node.
    """
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(GitCredential).where(GitCredential.id == cred_id, GitCredential.org_id == org_id))
    cred = r.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    try:
        if node_id:
            return await fetch_node_children_for_credential(cred, node_id)
        roots = await fetch_root_nodes_for_credential(cred)
        return {"repos": [], "subgroups": roots}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to expand node: {exc}") from exc


@router.get("/{cred_id}/repos", response_model=list[dict])
async def list_repos(
    cred_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch full tree (used by agent tools). UI should prefer /repos/expand for lazy loading."""
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(GitCredential).where(GitCredential.id == cred_id, GitCredential.org_id == org_id))
    cred = r.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    try:
        return await fetch_tree_for_credential(cred)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch repositories: {exc}") from exc


@router.delete("/{cred_id}", status_code=204)
async def delete_credential(
    cred_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(GitCredential).where(GitCredential.id == cred_id, GitCredential.org_id == org_id))
    cred = r.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.delete(cred)
    await db.commit()
