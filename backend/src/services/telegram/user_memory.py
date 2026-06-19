"""Telegram bot — persistent per-user memory, unified with web app user profiles."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def _user_memory_key(org_id: str, tg_user_id: int) -> str:
    return f"tg_user_memory:{org_id}:{tg_user_id}"


async def _find_or_autolink_user_id(org_id: str, tg_user_id: int) -> str | None:
    """
    Return the web user.id linked to this Telegram user.
    In personal orgs, auto-links the org owner on first contact.
    """
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.user import User
    from src.models.org import OrgMember, Organization

    async with AsyncSessionLocal() as db:
        # Check existing explicit link
        r = await db.execute(
            select(User.id).join(OrgMember, OrgMember.user_id == User.id).where(
                OrgMember.org_id == org_id,
                User.telegram_user_id == str(tg_user_id),
            )
        )
        uid = r.scalar_one_or_none()
        if uid:
            return uid

        # Auto-link in personal orgs (one owner = the bot owner)
        r_org = await db.execute(select(Organization).where(Organization.id == org_id))
        org = r_org.scalar_one_or_none()
        if not org or not org.is_personal:
            return None

        r_owner = await db.execute(
            select(User).join(OrgMember, OrgMember.user_id == User.id).where(
                OrgMember.org_id == org_id,
                OrgMember.role == "owner",
            )
        )
        owner = r_owner.scalar_one_or_none()
        if not owner:
            return None

        owner.telegram_user_id = str(tg_user_id)
        db.add(owner)
        await db.commit()
        logger.info(f"[tg_memory] auto-linked Telegram user {tg_user_id} → web user {owner.id}")
        return owner.id


async def _load_user_profile(org_id: str, tg_user_id: int) -> dict:
    user_id = await _find_or_autolink_user_id(org_id, tg_user_id)

    if user_id:
        from sqlalchemy import select
        from src.core.database import AsyncSessionLocal
        from src.models.user import User

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(User).where(User.id == user_id))
            user = r.scalar_one_or_none()
            if user:
                profile: dict = {"name": user.full_name}
                if user.notes:
                    profile["notes"] = user.notes
                if user.contact_info:
                    try:
                        contacts = json.loads(user.contact_info)
                        if contacts:
                            lines = "\n".join(
                                f"- {row['key']}: {row['value']}"
                                for row in contacts
                                if row.get("key") and row.get("value")
                            )
                            if lines:
                                extra = f"\n\n### Contact Info\n{lines}"
                                profile["notes"] = (profile.get("notes", "") + extra).strip()
                    except Exception:
                        pass
                return profile

    # Fall back to Redis for unlinked Telegram users
    from src.core.redis import get_redis
    raw = await get_redis().get(_user_memory_key(org_id, tg_user_id))
    if raw:
        try:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            pass
    return {}


async def _save_user_profile(org_id: str, tg_user_id: int, profile: dict) -> None:
    user_id = await _find_or_autolink_user_id(org_id, tg_user_id)

    if user_id:
        from sqlalchemy import select
        from src.core.database import AsyncSessionLocal
        from src.models.user import User

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(User).where(User.id == user_id))
            user = r.scalar_one_or_none()
            if user:
                if profile.get("notes"):
                    user.notes = profile["notes"]
                if profile.get("name") and profile["name"] != user.full_name:
                    user.full_name = profile["name"]
                db.add(user)
                await db.commit()
                logger.info(f"[tg_memory] saved profile to users table for {user_id}")
                return

    # Fall back to Redis for unlinked users
    from src.core.redis import get_redis
    from datetime import datetime, timezone
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    await get_redis().set(
        _user_memory_key(org_id, tg_user_id),
        json.dumps(profile, ensure_ascii=False),
    )
    logger.info(f"[tg_memory] saved profile to Redis for tg_user {tg_user_id} in org {org_id}")


def _user_profile_system_section(profile: dict) -> str | None:
    if not profile:
        return None
    lines = ["## Who you are talking to"]
    if profile.get("name"):
        lines.append(f"Name: {profile['name']}")
    if profile.get("language"):
        lines.append(f"Language: {profile['language']}")
    if profile.get("notes"):
        lines.append(f"\n{profile['notes']}")
    if profile.get("updated_at"):
        lines.append(f"\n(Profile last updated: {profile['updated_at'][:10]})")
    return "\n".join(lines)
