"""Telegram sync hub — group/topic management that mirrors Nexora projects."""
import json
import logging
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


# ─── DB helpers ───────────────────────────────────────────────────────────────

async def _load_integration(integration_id: str):
    from src.core.database import AsyncSessionLocal
    from src.models.integration import Integration
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Integration).where(Integration.id == integration_id))
        return r.scalar_one_or_none()


async def _load_config(integration_id: str) -> dict | None:
    i = await _load_integration(integration_id)
    if not i or not i.config:
        return None
    try:
        return json.loads(i.config)
    except Exception:
        return None


async def _save_config(integration_id: str, config: dict) -> None:
    from src.core.database import AsyncSessionLocal
    from src.models.integration import Integration
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Integration).where(Integration.id == integration_id))
        i = r.scalar_one_or_none()
        if i:
            i.config = json.dumps(config)
            await db.commit()


async def _get_org_projects(org_id: str) -> list[dict]:
    from src.core.database import AsyncSessionLocal
    from src.models.project import Project
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Project)
            .where(Project.org_id == org_id, Project.status == "active")
            .order_by(Project.created_at)
        )
        return [{"id": p.id, "name": p.name} for p in r.unique().scalars().all()]


async def _get_default_tg_integration(org_id: str) -> tuple[str | None, dict | None]:
    """Return (integration_id, config) for the org's default active telegram integration."""
    from src.core.database import AsyncSessionLocal
    from src.models.integration import Integration
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Integration).where(
                Integration.org_id == org_id,
                Integration.integration_type == "telegram",
                Integration.is_default == True,
                Integration.is_active == True,
            )
        )
        i = r.scalar_one_or_none()
        if not i or not i.config:
            return None, None
        try:
            return i.id, json.loads(i.config)
        except Exception:
            return None, None


# ─── Bot command handlers ──────────────────────────────────────────────────────

async def handle_start_command(update: Update, integration_id: str | None) -> None:
    """/start handler — detect Premium and guide through sync hub setup."""
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    is_premium = getattr(user, "is_premium", False) or False

    # If already configured for this user, confirm it
    if integration_id:
        cfg = await _load_config(integration_id)
        if cfg:
            hub = cfg.get("sync_hub", {})
            if hub.get("setup_complete") and hub.get("telegram_user_id") == user.id:
                n = len(hub.get("project_topics", {}))
                await update.message.reply_text(
                    f"✅ Your *Nexora Sync Hub* is already active!\n\n"
                    f"Group: `{hub.get('group_chat_id')}`\n"
                    f"Projects synced: *{n}*\n\n"
                    f"New projects you create on the web will automatically get a topic here.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

    if is_premium:
        await update.message.reply_text(
            "👋 Welcome to your *Nexora* assistant!\n\n"
            "Since you have *Telegram Premium*, I can set up a *Sync Hub* for you — "
            "a Telegram group where each project gets its own topic thread, "
            "keeping your entire workspace mirrored here in real time.\n\n"
            "📋 *Setup steps:*\n"
            "1️⃣ Create a new Telegram *Supergroup* (not a basic group)\n"
            "2️⃣ Go to group *Settings → Edit → Topics* and enable *Topics*\n"
            "3️⃣ Add me as an *Administrator* with full permissions (especially *Manage Topics*)\n"
            "4️⃣ Done — I'll automatically create a topic for every project!\n\n"
            "⏳ *Waiting for you to add me to a forum supergroup…*",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to your *Nexora* assistant!\n\n"
            "I'm ready to help with your projects. Just send me a message!\n\n"
            "💡 *Tip:* With *Telegram Premium* you can unlock the *Sync Hub* — "
            "a group where every project gets its own topic thread, "
            "mirroring your entire Nexora workspace in Telegram.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_my_chat_member(update: Update, bot: Bot, integration_id: str | None) -> None:
    """Handle the bot being promoted to admin in a group — configure sync hub."""
    if not update.my_chat_member:
        return

    from telegram import ChatMemberAdministrator
    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member
    from_user = update.my_chat_member.from_user

    if not isinstance(new_status, ChatMemberAdministrator):
        return
    if chat.type not in ("supergroup", "channel"):
        return

    # Check if this is a forum (topics-enabled) supergroup
    try:
        full_chat = await bot.get_chat(chat.id)
        is_forum = getattr(full_chat, "is_forum", False) or False
    except TelegramError as exc:
        logger.warning(f"[telegram_sync] could not fetch chat info for {chat.id}: {exc}")
        return

    if not is_forum:
        try:
            await bot.send_message(
                from_user.id,
                "⚠️ I was added to a group, but *Topics* are not enabled.\n\n"
                "Please go to the group *Settings → Edit → Topics*, enable topics, "
                "then remove and re-add me as an administrator.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            pass
        return

    if not integration_id:
        logger.warning("[telegram_sync] my_chat_member received but no integration_id")
        return

    integration = await _load_integration(integration_id)
    if not integration:
        return

    cfg = await _load_config(integration_id) or {}
    projects = await _get_org_projects(integration.org_id)

    project_topics: dict[str, int] = {}
    for project in projects:
        try:
            topic = await bot.create_forum_topic(
                chat_id=chat.id,
                name=project["name"][:128],
            )
            project_topics[project["id"]] = topic.message_thread_id
            logger.info(f"[telegram_sync] created topic '{project['name']}' in group {chat.id}")
        except TelegramError as exc:
            logger.warning(f"[telegram_sync] failed to create topic for project {project['id']}: {exc}")

    cfg["sync_hub"] = {
        "telegram_user_id": from_user.id,
        "group_chat_id": chat.id,
        "is_forum": True,
        "setup_complete": True,
        "project_topics": project_topics,
    }
    await _save_config(integration_id, cfg)

    topic_list = "\n".join(f"• {p['name']}" for p in projects) if projects else "_(no projects yet)_"
    try:
        await bot.send_message(
            chat.id,
            f"🚀 *Nexora Sync Hub is ready!*\n\n"
            f"This group is now synchronized with your Nexora workspace.\n\n"
            f"*Projects with topics:*\n{topic_list}\n\n"
            f"New projects created on the web will get their own topic here automatically.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as exc:
        logger.warning(f"[telegram_sync] failed to send welcome to group {chat.id}: {exc}")

    try:
        await bot.send_message(
            from_user.id,
            f"✅ *Sync hub configured!*\n\n"
            f"{len(project_topics)} project topic(s) created.\n"
            f"Your Nexora workspace is now mirrored in the group.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as exc:
        logger.warning(f"[telegram_sync] failed to DM user {from_user.id}: {exc}")


# ─── Platform hooks ────────────────────────────────────────────────────────────

async def create_project_topic(project_id: str, project_name: str, org_id: str) -> None:
    """Called after a project is created — create its Telegram topic in the sync hub."""
    int_id, cfg = await _get_default_tg_integration(org_id)
    if not int_id or not cfg:
        return

    hub = cfg.get("sync_hub", {})
    if not hub.get("setup_complete"):
        return

    group_chat_id = hub.get("group_chat_id")
    token = cfg.get("token")
    if not group_chat_id or not token:
        return

    try:
        bot = Bot(token=token)
        topic = await bot.create_forum_topic(
            chat_id=group_chat_id,
            name=project_name[:128],
        )
        topics: dict = hub.get("project_topics", {})
        topics[project_id] = topic.message_thread_id
        hub["project_topics"] = topics
        cfg["sync_hub"] = hub
        await _save_config(int_id, cfg)

        await bot.send_message(
            chat_id=group_chat_id,
            message_thread_id=topic.message_thread_id,
            text=f"📁 *{project_name}* — project created on Nexora.",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"[telegram_sync] topic created for project {project_id} in group {group_chat_id}")
    except Exception as exc:
        logger.warning(f"[telegram_sync] create_project_topic failed for {project_id}: {exc}")


async def post_to_project_topic(project_id: str, org_id: str, text: str, sender: str = "assistant") -> None:
    """Post an assistant (or user) message to the project's Telegram topic."""
    if not org_id or not project_id:
        return

    int_id, cfg = await _get_default_tg_integration(org_id)
    if not int_id or not cfg:
        return

    hub = cfg.get("sync_hub", {})
    if not hub.get("setup_complete"):
        return

    group_chat_id = hub.get("group_chat_id")
    token = cfg.get("token")
    topics: dict = hub.get("project_topics", {})
    topic_id = topics.get(project_id)

    if not group_chat_id or not token or not topic_id:
        return

    try:
        bot = Bot(token=token)
        prefix = "🤖 " if sender == "assistant" else "👤 "
        display = text[:4000] + ("…" if len(text) > 4000 else "")
        try:
            await bot.send_message(
                chat_id=group_chat_id,
                message_thread_id=topic_id,
                text=f"{prefix}{display}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            await bot.send_message(
                chat_id=group_chat_id,
                message_thread_id=topic_id,
                text=f"{prefix}{display}",
            )
    except Exception as exc:
        logger.warning(f"[telegram_sync] post_to_project_topic failed for {project_id}: {exc}")
