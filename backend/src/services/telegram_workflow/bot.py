import asyncio
import functools
import logging

from sqlalchemy import select
from telegram.error import Conflict
from telegram.ext import (
    Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler,
    MessageHandler, filters,
)

from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.services.telegram.chat_store import (
    _acquire_bot_lock, _release_bot_lock, _refresh_bot_lock,
)
from src.services.telegram.relay import _event_relays

from .helpers import _sync_allowed_to_redis
from .handlers.commands import handle_new, handle_start, handle_bot_member_update, handle_cancel, handle_remove_chat
from .handlers.message import handle_message
from .handlers.history import handle_history, handle_callback
from .handlers.errors import conflict_error_handler

logger = logging.getLogger(__name__)

_bots:               dict[str, Application]  = {}
_lock_refresh_tasks: dict[str, asyncio.Task] = {}


async def start_telegram_bot(
    workflow_id: str,
    token: str,
    allowed_chat_ids: list[int],
    integration_id: str | None = None,
    pre_claimed: bool = False,
) -> None:
    if workflow_id in _bots:
        await stop_telegram_bot(workflow_id)

    if not pre_claimed and not await _acquire_bot_lock(workflow_id):
        logger.debug(f"[tg] another worker holds lock for {workflow_id}, skipping")
        return

    # Resolve the channel's agent + org from the integration. Without these the bot has no
    # agent to drive replies and no org to resolve providers ("No providers configured"),
    # so it silently reads messages and never responds.
    agent_name: str | None = None
    wf_agent_id: str | None = None
    wf_org_id: str = ""

    if integration_id:
        import json as _json
        from src.models.integration import Integration as _Integration
        async with AsyncSessionLocal() as db:
            ir = await db.execute(select(_Integration).where(_Integration.id == integration_id))
            integ = ir.scalar_one_or_none()
            if integ:
                wf_org_id = integ.org_id or ""
                _cfg = {}
                if integ.config:
                    try:
                        _cfg = _json.loads(integ.config) if isinstance(integ.config, str) else dict(integ.config)
                    except Exception:
                        _cfg = {}
                wf_agent_id = _cfg.get("channel_agent_id") or None

    if wf_agent_id:
        async with AsyncSessionLocal() as db:
            r2 = await db.execute(select(Agent).where(Agent.id == wf_agent_id))
            ag = r2.scalar_one_or_none()
            if ag:
                agent_name = ag.name

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", functools.partial(
        handle_start,
        integration_id=integration_id,
    )))
    app.add_handler(CommandHandler("new", functools.partial(
        handle_new,
        workflow_id=workflow_id,
        wf_agent_id=wf_agent_id,
    )))
    app.add_handler(CommandHandler("history", functools.partial(
        handle_history,
        workflow_id=workflow_id,
    )))
    _cancel_handler = functools.partial(
        handle_cancel,
        workflow_id=workflow_id,
        wf_agent_id=wf_agent_id,
    )
    app.add_handler(CommandHandler("cancel", _cancel_handler))
    app.add_handler(CommandHandler("stop", _cancel_handler))
    app.add_handler(CommandHandler("remove_chat", functools.partial(
        handle_remove_chat,
        workflow_id=workflow_id,
    )))
    app.add_handler(CallbackQueryHandler(
        functools.partial(handle_callback, workflow_id=workflow_id),
        pattern=r"^hist:",
    ))
    app.add_handler(ChatMemberHandler(
        functools.partial(handle_bot_member_update, integration_id=integration_id),
        ChatMemberHandler.MY_CHAT_MEMBER,
    ))
    app.add_handler(MessageHandler(~filters.COMMAND, functools.partial(
        handle_message,
        workflow_id=workflow_id,
        wf_agent_id=wf_agent_id,
        wf_org_id=wf_org_id,
        agent_name=agent_name,
        integration_id=integration_id,
        allowed_chat_ids=allowed_chat_ids,
    )))
    app.add_error_handler(functools.partial(conflict_error_handler, workflow_id))

    await app.initialize()
    await app.start()

    if integration_id:
        await _sync_allowed_to_redis(integration_id, allowed_chat_ids)

    async def _polling() -> None:
        delays = [0, 5, 30]
        for i, delay in enumerate(delays):
            if delay:
                logger.warning(
                    f"[tg] Conflict for {workflow_id} — previous session still live, "
                    f"retrying in {delay}s (attempt {i + 1}/{len(delays)})"
                )
                await asyncio.sleep(delay)
            try:
                await app.bot.delete_webhook(drop_pending_updates=True)
                await app.updater.start_polling(drop_pending_updates=True)
                logger.info(f"[tg] bot started for workflow {workflow_id}")
                return
            except Conflict:
                continue
            except Exception as exc:
                logger.error(f"[tg] polling error for {workflow_id}: {exc}")
                return
        logger.error(f"[tg] could not acquire polling session for {workflow_id} after {len(delays)} attempts")

    asyncio.create_task(_polling())
    _bots[workflow_id] = app
    _lock_refresh_tasks[workflow_id] = asyncio.create_task(_refresh_bot_lock(workflow_id))


async def stop_telegram_bot(workflow_id: str) -> None:
    refresh = _lock_refresh_tasks.pop(workflow_id, None)
    if refresh:
        refresh.cancel()
    app = _bots.pop(workflow_id, None)
    if not app:
        await _release_bot_lock(workflow_id)
        return
    try:
        if app.updater and app.updater.running:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info(f"[tg] bot stopped for workflow {workflow_id}")
    except Exception as exc:
        logger.warning(f"[tg] error stopping bot for {workflow_id}: {exc}")
    finally:
        await _release_bot_lock(workflow_id)


async def stop_all_bots() -> None:
    for task in list(_event_relays.values()):
        task.cancel()
    _event_relays.clear()
    for wid in list(_bots.keys()):
        await stop_telegram_bot(wid)


def _bot_alive(workflow_id: str) -> bool:
    """True only if THIS process holds a poller whose updater is actively running."""
    app = _bots.get(workflow_id)
    if not app:
        return False
    try:
        return bool(app.updater and app.updater.running)
    except Exception:
        return False


async def reconcile_telegram_bots() -> None:
    """Ensure every active Telegram integration has a live local poller.

    Self-heals two failure modes that previously killed the bot until a manual
    restart:
      1. **Restart lock-race** — the prior process's Redis lock (30s TTL, refreshed
         every 15s) outlives the dead process by up to 30s, so workers that boot in
         that window fail `_acquire_bot_lock` and give up permanently. The periodic
         reconcile retries once the stale lock expires.
      2. **Silent updater death** — python-telegram-bot's polling task can stop
         without raising; `_bot_alive` detects the stopped updater and restarts it.

    Safe to call repeatedly and from every worker: the Redis lock keeps exactly one
    worker polling, and live pollers are skipped.
    """
    import json as _json
    from src.models.integration import Integration

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Integration).where(
                Integration.integration_type == "telegram",
                Integration.is_active == True,
            )
        )
        integrations = r.scalars().all()

    active_ids: set[str] = set()
    for i in integrations:
        cfg: dict = {}
        if i.config:
            try:
                cfg = _json.loads(i.config)
            except Exception:
                cfg = {}
        token = cfg.get("bot_token") or cfg.get("token")
        agent_id = cfg.get("channel_agent_id")
        if not token or not agent_id:
            continue
        active_ids.add(i.id)
        if _bot_alive(i.id):
            continue
        allowed = [int(x) for x in cfg.get("allowed_chat_ids", [])]
        try:
            await start_telegram_bot(
                workflow_id=i.id,
                token=token,
                allowed_chat_ids=allowed,
                integration_id=i.id,
                pre_claimed=False,
            )
        except Exception as exc:
            logger.warning(f"[tg] reconcile failed to start {i.id}: {exc}")

    # Tear down pollers in THIS process for integrations that are gone/deactivated.
    for wid in list(_bots.keys()):
        if wid not in active_ids:
            await stop_telegram_bot(wid)
