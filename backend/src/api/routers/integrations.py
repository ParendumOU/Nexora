"""External communication integrations (Telegram, Slack, Discord, WhatsApp, etc.)."""
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.user import User
from src.models.integration import Integration
from src.models.telegram_pending import TelegramPending

router = APIRouter(prefix="/integrations", tags=["integrations"])

SUPPORTED_TYPES = {"telegram", "slack", "discord", "whatsapp"}


class IntegrationCreate(BaseModel):
    name: str
    integration_type: str
    config: dict = {}


class IntegrationUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    is_active: bool | None = None


class AcceptPendingRequest(BaseModel):
    code: str


def _mask_config(cfg: dict) -> dict:
    masked = dict(cfg)
    for key in ("token", "api_key", "bot_token"):
        val = masked.get(key)
        if isinstance(val, str) and len(val) > 12:
            masked[key] = val[:6] + "..." + val[-4:]
    return masked


def _int_dict(i: Integration, pending_count: int = 0) -> dict:
    cfg: dict = {}
    if i.config:
        try:
            cfg = json.loads(i.config)
        except Exception:
            pass
    return {
        "id": i.id,
        "name": i.name,
        "integration_type": i.integration_type,
        "config": _mask_config(cfg),
        "is_active": i.is_active,
        "is_default": i.is_default,
        "pending_count": pending_count,
        "created_at": i.created_at.isoformat(),
    }


@router.get("")
async def list_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration)
        .where(Integration.org_id == org_id)
        .order_by(Integration.created_at.desc())
    )
    integrations = r.scalars().all()

    result = []
    for i in integrations:
        pending_count = 0
        if i.integration_type == "telegram":
            cnt_r = await db.execute(
                select(func.count()).select_from(TelegramPending).where(
                    TelegramPending.integration_id == i.id,
                    TelegramPending.status == "pending",
                )
            )
            pending_count = cnt_r.scalar() or 0
        result.append(_int_dict(i, pending_count))
    return result


@router.post("", status_code=201)
async def create_integration(
    req: IntegrationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.integration_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=422, detail=f"integration_type must be one of {sorted(SUPPORTED_TYPES)}")
    org_id = await get_active_org_id(current_user, db)
    i = Integration(
        id=str(uuid.uuid4()),
        org_id=org_id,
        integration_type=req.integration_type,
        name=req.name,
        config=json.dumps(req.config) if req.config else None,
        is_active=True,
    )
    db.add(i)
    await db.commit()
    await db.refresh(i)
    return _int_dict(i)


@router.patch("/{int_id}")
async def update_integration(
    int_id: str,
    req: IntegrationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration).where(Integration.id == int_id, Integration.org_id == org_id)
    )
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")
    if req.name is not None:
        i.name = req.name
    if req.config is not None:
        existing: dict = json.loads(i.config) if i.config else {}
        for k, v in req.config.items():
            # Skip blank or placeholder values so we don't erase existing secrets
            if v not in ("", None) and not (isinstance(v, str) and "..." in v):
                existing[k] = v
        i.config = json.dumps(existing)
    if req.is_active is not None:
        i.is_active = req.is_active
    await db.commit()
    await db.refresh(i)

    # Sync allowlist to Redis so live bots pick up the change immediately
    if i.integration_type == "telegram":
        try:
            cfg_synced: dict = json.loads(i.config) if i.config else {}
            allowed_synced = [int(x) for x in cfg_synced.get("allowed_chat_ids", [])]
            from src.services.telegram_workflow import _sync_allowed_to_redis
            await _sync_allowed_to_redis(int_id, allowed_synced)
        except Exception:
            pass

    return _int_dict(i)


@router.post("/{int_id}/set-default", status_code=200)
async def set_default_integration(
    int_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration).where(Integration.id == int_id, Integration.org_id == org_id)
    )
    target = r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Integration not found")
    # Unset all others for this org first
    r2 = await db.execute(
        select(Integration).where(Integration.org_id == org_id, Integration.is_default == True)
    )
    for i in r2.scalars().all():
        i.is_default = False
    target.is_default = True
    await db.commit()
    await db.refresh(target)
    return _int_dict(target)


@router.delete("/{int_id}", status_code=204)
async def delete_integration(
    int_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration).where(Integration.id == int_id, Integration.org_id == org_id)
    )
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")
    await db.delete(i)
    await db.commit()


# ── Pending access requests ───────────────────────────────────────────────────

@router.get("/{int_id}/pending")
async def list_pending(
    int_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration).where(Integration.id == int_id, Integration.org_id == org_id)
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Integration not found")

    pr = await db.execute(
        select(TelegramPending)
        .where(TelegramPending.integration_id == int_id)
        .order_by(TelegramPending.created_at.desc())
    )
    records = pr.scalars().all()

    result = []
    for p in records:
        linked_user = None
        ur = await db.execute(
            select(User).where(User.telegram_user_id == p.tg_user_id)
        )
        u = ur.scalar_one_or_none()
        if u:
            linked_user = {
                "id": u.id,
                "full_name": u.full_name,
                "email": u.email,
                "avatar_emoji": u.avatar_emoji,
            }
        result.append({
            "id": p.id,
            "tg_user_id": p.tg_user_id,
            "tg_username": p.tg_username,
            "tg_display_name": p.tg_display_name,
            "code": p.code,
            "status": p.status,
            "linked_user": linked_user,
            "created_at": p.created_at.isoformat(),
        })
    return result


@router.post("/{int_id}/accept")
async def accept_pending(
    int_id: str,
    req: AcceptPendingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration).where(Integration.id == int_id, Integration.org_id == org_id)
    )
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")

    pr = await db.execute(
        select(TelegramPending).where(
            TelegramPending.org_id == org_id,
            TelegramPending.code == req.code.upper(),
            TelegramPending.status == "pending",
        )
    )
    pending = pr.scalar_one_or_none()
    if not pending:
        raise HTTPException(status_code=404, detail="Code not found or already used")

    cfg: dict = json.loads(i.config) if i.config else {}
    allowed: list = cfg.get("allowed_chat_ids", [])
    tg_id = int(pending.tg_user_id)
    if tg_id not in allowed:
        allowed.append(tg_id)
    cfg["allowed_chat_ids"] = allowed
    i.config = json.dumps(cfg)
    pending.status = "accepted"
    await db.commit()

    from src.services.telegram_workflow import _sync_allowed_to_redis
    await _sync_allowed_to_redis(int_id, allowed)

    return {"status": "accepted", "tg_user_id": pending.tg_user_id}


@router.delete("/{int_id}/pending/{pending_id}", status_code=204)
async def revoke_pending(
    int_id: str,
    pending_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Integration).where(Integration.id == int_id, Integration.org_id == org_id)
    )
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")

    pr = await db.execute(
        select(TelegramPending).where(
            TelegramPending.id == pending_id,
            TelegramPending.integration_id == int_id,
        )
    )
    pending = pr.scalar_one_or_none()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending record not found")

    cfg: dict = json.loads(i.config) if i.config else {}
    tg_id = int(pending.tg_user_id)
    cfg["allowed_chat_ids"] = [x for x in cfg.get("allowed_chat_ids", []) if int(x) != tg_id]
    i.config = json.dumps(cfg)
    pending.status = "revoked"
    await db.commit()

    from src.services.telegram_workflow import _sync_allowed_to_redis
    await _sync_allowed_to_redis(int_id, cfg["allowed_chat_ids"])


async def _get_tg_integration(int_id: str, org_id: str, db: AsyncSession) -> Integration:
    r = await db.execute(select(Integration).where(Integration.id == int_id, Integration.org_id == org_id))
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")
    if i.integration_type != "telegram":
        raise HTTPException(status_code=400, detail="Only telegram integrations support bots")
    return i


@router.post("/{int_id}/start-bot", status_code=200)
async def start_bot(
    int_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    i = await _get_tg_integration(int_id, org_id, db)
    cfg: dict = json.loads(i.config) if i.config else {}
    token = cfg.get("bot_token") or cfg.get("token")
    agent_id = cfg.get("channel_agent_id")
    if not token:
        raise HTTPException(status_code=400, detail="No bot_token configured")
    if not agent_id:
        raise HTTPException(status_code=400, detail="No agent assigned — set channel_agent_id first")
    allowed = [int(x) for x in cfg.get("allowed_chat_ids", [])]
    from src.services.telegram_workflow.bot import start_telegram_bot
    await start_telegram_bot(
        workflow_id=int_id,
        token=token,
        allowed_chat_ids=allowed,
        integration_id=int_id,
        pre_claimed=False,
    )
    i.is_active = True
    await db.commit()
    return {"ok": True}


@router.post("/{int_id}/stop-bot", status_code=200)
async def stop_bot(
    int_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    i = await _get_tg_integration(int_id, org_id, db)
    from src.services.telegram_workflow.bot import stop_telegram_bot
    await stop_telegram_bot(int_id)
    i.is_active = False
    await db.commit()
    return {"ok": True}


@router.get("/{int_id}/conversations")
async def list_conversations(
    int_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Integration).where(Integration.id == int_id, Integration.org_id == org_id))
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")

    from src.core.redis import get_redis
    from src.models.chat import Chat, Message as DbMsg
    from sqlalchemy import select as sa_select

    redis = get_redis()
    vchat_ids: list[str] = []
    async for key in redis.scan_iter(f"tg_vchat:{int_id}:*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        val = await redis.get(key_str)
        if val:
            vchat_ids.append(val.decode() if isinstance(val, bytes) else val)

    if not vchat_ids:
        return []

    chats_r = await db.execute(
        sa_select(Chat)
        .where(Chat.id.in_(vchat_ids[:limit]))
        .order_by(Chat.updated_at.desc())
    )
    chats = chats_r.scalars().all()

    result = []
    for chat in chats:
        last_r = await db.execute(
            sa_select(DbMsg)
            .where(DbMsg.chat_id == chat.id, DbMsg.excluded == False)
            .order_by(DbMsg.created_at.desc())
            .limit(1)
        )
        last = last_r.scalar_one_or_none()
        result.append({
            "chat_id": chat.id,
            "title": chat.title,
            "agent_id": chat.agent_id,
            "last_message": last.content[:300] if last else None,
            "last_message_role": last.role if last else None,
            "updated_at": chat.updated_at.isoformat(),
            "created_at": chat.created_at.isoformat(),
        })
    return result


@router.delete("/{int_id}/conversations/{chat_id}", status_code=204)
async def delete_conversation(
    int_id: str,
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Integration).where(Integration.id == int_id, Integration.org_id == org_id))
    i = r.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Integration not found")

    from src.models.chat import Chat as DbChat
    from sqlalchemy import select as sa_select, delete as sa_delete

    chat_r = await db.execute(sa_select(DbChat).where(DbChat.id == chat_id))
    chat = chat_r.scalar_one_or_none()
    if chat:
        await db.delete(chat)
        await db.commit()

    from src.core.redis import get_redis
    redis = get_redis()
    async for key in redis.scan_iter(f"tg_vchat:{int_id}:*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        val = await redis.get(key_str)
        if val and (val.decode() if isinstance(val, bytes) else val) == chat_id:
            await redis.delete(key_str)
