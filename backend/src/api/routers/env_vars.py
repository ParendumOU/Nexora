"""Org- and user-scoped environment variables for tool credentials.

Lets users store API keys / secrets in the org (shared) or their profile
(personal) instead of a server `.env`. Values are encrypted at rest; the API
never returns a value, only metadata (key, name, description, has_value).
At tool-execution time values resolve org-first, then user (see
services/env_vars.py).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.deps import get_db, get_current_user
from src.core.security import encrypt
from src.models.env_var import EnvVar
from src.models.org import OrgMember, OrgRole
from src.models.user import User

router = APIRouter(prefix="/env-vars", tags=["env-vars"])


class EnvVarIn(BaseModel):
    scope: str = Field(..., pattern="^(org|user)$")
    org_id: str | None = None
    key: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=120)
    value: str = Field(..., min_length=1)
    description: str | None = Field(None, max_length=500)


class EnvVarPatch(BaseModel):
    value: str | None = None
    description: str | None = Field(None, max_length=500)
    name: str | None = Field(None, min_length=1, max_length=120)


class ResolveIn(BaseModel):
    keys: list[str]
    org_id: str | None = None


def _out(r: EnvVar) -> dict:
    return {
        "id": r.id, "scope": r.scope, "org_id": r.org_id, "key": r.key,
        "name": r.name, "description": r.description, "has_value": bool(r.value_enc),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


async def _member_role(db, org_id: str, user_id: str) -> OrgRole | None:
    m = (await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    )).scalar_one_or_none()
    return m.role if m else None


async def _require_org_write(db, org_id: str, user: User) -> None:
    role = await _member_role(db, org_id, user.id)
    if role not in (OrgRole.owner, OrgRole.admin):
        raise HTTPException(403, "Org owner/admin required to manage org environment variables.")


@router.get("")
async def list_env_vars(scope: str | None = None, org_id: str | None = None,
                        db=Depends(get_db), user: User = Depends(get_current_user)):
    """List the caller's accessible env vars (user scope = own; org scope = orgs
    they belong to). Values are never returned."""
    out: list[dict] = []
    if scope in (None, "user"):
        rows = (await db.execute(
            select(EnvVar).where(EnvVar.scope == "user", EnvVar.user_id == user.id)
        )).scalars().all()
        out += [_out(r) for r in rows]
    if scope in (None, "org"):
        if org_id:
            if await _member_role(db, org_id, user.id) is None:
                raise HTTPException(403, "Not a member of that organization.")
            org_ids = [org_id]
        else:
            mrows = (await db.execute(
                select(OrgMember.org_id).where(OrgMember.user_id == user.id)
            )).scalars().all()
            org_ids = list(mrows)
        if org_ids:
            rows = (await db.execute(
                select(EnvVar).where(EnvVar.scope == "org", EnvVar.org_id.in_(org_ids))
            )).scalars().all()
            out += [_out(r) for r in rows]
    return {"env_vars": out}


@router.post("")
async def create_env_var(body: EnvVarIn, db=Depends(get_db),
                         user: User = Depends(get_current_user)):
    if body.scope == "org":
        if not body.org_id:
            raise HTTPException(400, "org_id required for org scope.")
        await _require_org_write(db, body.org_id, user)
        owner = {"org_id": body.org_id, "user_id": None}
        dup_q = select(EnvVar).where(EnvVar.scope == "org", EnvVar.org_id == body.org_id,
                                     EnvVar.name == body.name)
    else:
        owner = {"org_id": None, "user_id": user.id}
        dup_q = select(EnvVar).where(EnvVar.scope == "user", EnvVar.user_id == user.id,
                                     EnvVar.name == body.name)
    if (await db.execute(dup_q)).scalar_one_or_none():
        raise HTTPException(409, f"A variable named '{body.name}' already exists in this scope.")
    row = EnvVar(id=str(uuid.uuid4()), scope=body.scope, key=body.key, name=body.name,
                 value_enc=encrypt(body.value), description=body.description, **owner)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.patch("/{var_id}")
async def update_env_var(var_id: str, body: EnvVarPatch, db=Depends(get_db),
                         user: User = Depends(get_current_user)):
    row = (await db.execute(select(EnvVar).where(EnvVar.id == var_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Environment variable not found.")
    if row.scope == "org":
        await _require_org_write(db, row.org_id, user)
    elif row.user_id != user.id:
        raise HTTPException(403, "Not your variable.")
    if body.value is not None:
        row.value_enc = encrypt(body.value)
    if body.description is not None:
        row.description = body.description
    if body.name is not None and body.name != row.name:
        dup_q = select(EnvVar).where(EnvVar.scope == row.scope, EnvVar.name == body.name,
                                     EnvVar.org_id == row.org_id, EnvVar.user_id == row.user_id,
                                     EnvVar.id != row.id)
        if (await db.execute(dup_q)).scalar_one_or_none():
            raise HTTPException(409, f"A variable named '{body.name}' already exists in this scope.")
        row.name = body.name
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{var_id}")
async def delete_env_var(var_id: str, db=Depends(get_db),
                         user: User = Depends(get_current_user)):
    row = (await db.execute(select(EnvVar).where(EnvVar.id == var_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Environment variable not found.")
    if row.scope == "org":
        await _require_org_write(db, row.org_id, user)
    elif row.user_id != user.id:
        raise HTTPException(403, "Not your variable.")
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "id": var_id}


@router.post("/resolve")
async def resolve_existing(body: ResolveIn, db=Depends(get_db),
                           user: User = Depends(get_current_user)):
    """For the install modal: for each requested KEY return the variables already
    configured (org + user) that match it, so the UI shows what's set vs missing.
    No values are returned."""
    keys = [k for k in (body.keys or []) if k]
    org_ids: list[str] = []
    if body.org_id and await _member_role(db, body.org_id, user.id) is not None:
        org_ids = [body.org_id]
    cond = (EnvVar.scope == "user") & (EnvVar.user_id == user.id)
    if org_ids:
        cond = cond | ((EnvVar.scope == "org") & (EnvVar.org_id.in_(org_ids)))
    rows = []
    if keys:
        rows = (await db.execute(
            select(EnvVar).where(EnvVar.key.in_(keys), cond)
        )).scalars().all()
    matches: dict[str, list[dict]] = {k: [] for k in keys}
    for r in rows:
        matches.setdefault(r.key, []).append(
            {"id": r.id, "scope": r.scope, "name": r.name, "org_id": r.org_id})
    return {"keys": [{"key": k, "configured": matches.get(k, [])} for k in keys]}
