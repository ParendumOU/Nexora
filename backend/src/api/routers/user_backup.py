"""User backup — export and import personal profile data."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db, require_superuser
from src.models.user import User
from src.models.user_api_key import UserApiKey
from src.models.org import Organization, OrgMember

router = APIRouter(prefix="/users", tags=["backup"])

_FORMAT_USER = "nexora-profile-backup-v1"
_FORMAT_ADMIN = "nexora-admin-backup-v1"


def _profile_dict(u: User) -> dict:
    return {
        "full_name": u.full_name,
        "avatar_url": u.avatar_url,
        "avatar_emoji": u.avatar_emoji,
        "telegram_user_id": u.telegram_user_id,
        "notes": u.notes,
        "contact_info": u.contact_info,
    }


async def _user_export(user: User, db: AsyncSession) -> dict:
    """Build a single-user export payload."""
    keys_r = await db.execute(select(UserApiKey).where(UserApiKey.user_id == user.id))
    memberships_r = await db.execute(
        select(OrgMember, Organization)
        .join(Organization, Organization.id == OrgMember.org_id)
        .where(OrgMember.user_id == user.id)
    )
    memberships = [
        {
            "org_name": org.name,
            "org_slug": org.slug,
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
        }
        for m, org in memberships_r.all()
    ]
    api_keys = [
        {
            "name": k.name,
            "prefix": k.prefix,
            "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in keys_r.scalars().all()
    ]
    return {
        "email": user.email,
        "profile": _profile_dict(user),
        "api_keys": api_keys,
        "memberships": memberships,
    }


@router.get("/me/backup/export")
async def export_my_backup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payload = {
        "app": "nexora",
        "format": _FORMAT_USER,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        **(await _user_export(current_user, db)),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"nexora_backup_{stamp}.json"
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/me/backup/import", status_code=200)
async def import_my_backup(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.get("app") != "nexora" or payload.get("format") != _FORMAT_USER:
        raise HTTPException(400, "Invalid backup format — expected nexora-profile-backup-v1")

    profile = payload.get("profile", {})
    if not isinstance(profile, dict):
        raise HTTPException(400, "profile must be an object")
    allowed = {"full_name", "avatar_url", "avatar_emoji", "notes", "contact_info"}
    # Field length caps (#208) — reject an oversized payload instead of storing it.
    _caps = {"full_name": 255, "avatar_url": 2048, "avatar_emoji": 16, "notes": 20000, "contact_info": 10000}
    restored = []
    for field in allowed:
        if field in profile:
            value = profile[field]
            cap = _caps.get(field)
            if isinstance(value, str) and cap and len(value) > cap:
                raise HTTPException(400, f"Field '{field}' exceeds maximum length ({cap})")
            if isinstance(value, (dict, list)) and len(str(value)) > 20000:
                raise HTTPException(400, f"Field '{field}' is too large")
            setattr(current_user, field, value)
            restored.append(field)

    db.add(current_user)
    await db.commit()
    return {"restored_fields": restored}


@router.get("/backup/export")
async def export_all_backup(
    current_user: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    users_r = await db.execute(select(User).order_by(User.created_at))
    users = users_r.scalars().all()

    orgs_r = await db.execute(select(Organization).order_by(Organization.created_at))
    orgs = [
        {"id": o.id, "name": o.name, "slug": o.slug, "is_personal": o.is_personal}
        for o in orgs_r.scalars().all()
    ]

    users_data = []
    for u in users:
        entry = await _user_export(u, db)
        entry["is_active"] = u.is_active
        entry["is_superuser"] = u.is_superuser
        entry["created_at"] = u.created_at.isoformat()
        users_data.append(entry)

    payload = {
        "app": "nexora",
        "format": _FORMAT_ADMIN,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "users": users_data,
        "orgs": orgs,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"nexora_admin_backup_{stamp}.json"
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
