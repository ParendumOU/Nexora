"""remember_user — patch keyed facts about the current user's profile.

Patches discrete (key, value) facts so a single update never wipes the rest of
the profile (the old `user.notes = notes` blanket-overwrite bug). Accepts:

- op = "upsert" (default): create/replace one fact's value, leaving siblings intact
- op = "append": append to an existing fact's value (newline-joined), or create it
- op = "remove": delete a fact by key

Provide a single `key`+`value`, OR a `facts` list of {key, value} for batch.
Legacy `notes` (free-form blob) maps to upsert on the reserved key `freeform`.
"""
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.user import User
from src.models.user_profile_fact import UserProfileFact

logger = logging.getLogger(__name__)

_VALID_OPS = {"upsert", "append", "remove"}


def _utcnow():
    return datetime.now(timezone.utc)


def _collect_facts(args: dict) -> list[dict]:
    """Normalise the various input shapes into a list of {key, value} dicts."""
    facts: list[dict] = []

    raw = args.get("facts")
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("key"):
                facts.append({"key": str(row["key"]).strip(), "value": (row.get("value") or "")})

    key = (args.get("key") or "").strip()
    if key:
        facts.append({"key": key, "value": (args.get("value") or "")})

    # Legacy single free-form blob → reserved 'freeform' key (no longer wipes structured facts).
    notes = (args.get("notes") or "").strip()
    if notes:
        facts.append({"key": "freeform", "value": notes})

    return facts


async def execute(args: dict, chat_id: str, agent_id: str | None, agent_name: str | None) -> dict:
    op = (args.get("op") or "upsert").strip().lower()
    if op not in _VALID_OPS:
        return {"error": f"op must be one of: {', '.join(sorted(_VALID_OPS))}"}

    facts = _collect_facts(args)
    new_name = (args.get("name") or "").strip()

    if not facts and not new_name:
        return {"error": "Provide at least one of: key+value, facts[], notes, or name"}

    async with AsyncSessionLocal() as db:
        rc = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = rc.scalar_one_or_none()
        if not chat or not chat.user_id:
            return {"error": "Could not resolve user for this chat"}

        ru = await db.execute(select(User).where(User.id == chat.user_id))
        user = ru.scalar_one_or_none()
        if not user:
            return {"error": "User not found"}

        if new_name:
            user.full_name = new_name
            db.add(user)

        applied: list[dict] = []
        for f in facts:
            key, value = f["key"], (f["value"] or "").strip()

            existing = (await db.execute(
                select(UserProfileFact).where(
                    UserProfileFact.user_id == user.id,
                    UserProfileFact.key == key,
                )
            )).scalar_one_or_none()

            if op == "remove":
                if existing:
                    await db.delete(existing)
                    applied.append({"key": key, "op": "removed"})
                continue

            if not value:
                # upsert/append with empty value is a no-op (use op=remove to delete)
                continue

            if existing:
                if op == "append":
                    existing.value = f"{existing.value}\n{value}".strip()
                else:  # upsert
                    existing.value = value
                existing.source = agent_name or existing.source
                existing.updated_at = _utcnow()
                db.add(existing)
                applied.append({"key": key, "op": "appended" if op == "append" else "updated"})
            else:
                db.add(UserProfileFact(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    key=key,
                    value=value,
                    source=agent_name or "agent",
                ))
                applied.append({"key": key, "op": "created"})

        await db.commit()

    logger.info(f"[remember_user] user {chat.user_id} via chat {chat_id}: {applied} name={'set' if new_name else 'unchanged'}")
    return {"data": {"status": "saved", "user_id": chat.user_id, "applied": applied, "name_updated": bool(new_name)}}
