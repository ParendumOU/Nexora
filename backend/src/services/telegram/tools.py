"""Telegram bot — tool execution and channel system prompt."""
from __future__ import annotations

import json
import logging

from src.services.telegram.helpers import _send, _TOOL_FENCE_RE

logger = logging.getLogger(__name__)


# ── System prompt snippet ─────────────────────────────────────────────────────

def _telegram_system_snippet(message_id: int, thread_id: int | None, user_display: str) -> str:
    return (
        "## Channel: Telegram\n"
        "Write in plain, conversational prose. "
        "No markdown headers (##, ###), no horizontal rules (---), no excessive bullet lists. "
        "Keep replies concise and direct — this is a chat, not a document.\n\n"
        "### Extra Telegram actions\n"
        "Your text response is sent automatically. "
        "Use these tools ONLY for ADDITIONAL actions beyond your text reply:\n"
        "`telegram_send_file`            url* | caption | filename  — attach a document/file\n"
        "`telegram_send_audio`           url* | caption             — send an audio file\n"
        "`telegram_send_photo`           url* | caption             — send a photo/image\n"
        "`telegram_reply_to`             message_id* | text*        — quote-reply a specific message\n"
        "`telegram_react`                message_id* | emoji        — react to a message (default 👍)\n"
        "`telegram_create_topic`         name*                      — create a forum topic; returns new thread_id\n"
        "`telegram_edit_topic`           topic_id* | name*          — rename a forum topic\n"
        "`telegram_close_topic`          topic_id*                  — close/lock a forum topic\n"
        "`telegram_reopen_topic`         topic_id*                  — reopen a closed forum topic\n"
        "`telegram_delete_topic`         topic_id*                  — delete a topic and all its messages\n"
        "`telegram_pin_message`          message_id* | silent       — pin a message (silent=true skips notification)\n"
        "`telegram_unpin_message`        message_id                 — unpin a message (omit to unpin all)\n"
        "`telegram_set_chat_title`       title*                     — rename the group/channel\n"
        "`telegram_set_chat_description` description*               — update the group description\n\n"
        "### User memory\n"
        "`remember_user` notes* | name | language — update your permanent notes about this person.\n"
        "Call this only when you learn something genuinely new: their name, role, language,\n"
        "working preferences, or ongoing projects. Do NOT call it on greetings or small talk.\n"
        "Write the `notes` field as a structured prose summary of everything you know —\n"
        "it REPLACES previous notes entirely, so include all prior knowledge plus new insights.\n"
        "Pass `name` and `language` as separate fields when you learn them.\n\n"
        f"Current incoming message_id: {message_id}\n"
        f"Current thread_id (forum topic): {thread_id or 'none (not a forum topic)'}\n"
        f"User: {user_display}"
    )


# ── Tool execution ────────────────────────────────────────────────────────────

async def _execute_telegram_tools(
    fence_text: str,
    bot,
    tg_chat_id: int,
    thread_id: int | None = None,
    tg_user_id: int | None = None,
    org_id: str | None = None,
) -> None:
    m = _TOOL_FENCE_RE.search(fence_text)
    if not m:
        return
    try:
        calls = json.loads(m.group(1))
    except Exception as exc:
        logger.warning(f"[tg_tools] JSON parse error: {exc}")
        return

    sent_errors: set[str] = set()
    for call in calls:
        name = (call.get("name") or "").strip()
        args = call.get("args") or {}

        if name == "remember_user" and tg_user_id and org_id:
            notes = (args.get("notes") or "").strip()
            if notes:
                from src.services.telegram.user_memory import _load_user_profile, _save_user_profile
                profile = await _load_user_profile(org_id, tg_user_id)
                profile["notes"] = notes
                if args.get("name"):
                    profile["name"] = args["name"].strip()
                if args.get("language"):
                    profile["language"] = args["language"].strip()
                await _save_user_profile(org_id, tg_user_id, profile)
            continue

        if not name.startswith("telegram_"):
            continue
        try:
            await _run_telegram_tool(name, args, bot, tg_chat_id, thread_id, sent_errors)
        except Exception as exc:
            logger.warning(f"[tg_tools] {name} failed: {exc}")


async def _run_telegram_tool(
    name: str, args: dict, bot, tg_chat_id: int,
    thread_id: int | None = None, sent_errors: set | None = None
) -> None:
    url     = (args.get("url") or "").strip()
    caption = (args.get("caption") or "").strip() or None
    text    = (args.get("text") or "").strip()

    async def _err(msg: str) -> None:
        if sent_errors is not None:
            if msg in sent_errors:
                return
            sent_errors.add(msg)
        await _send(tg_chat_id, bot, msg, thread_id)

    kw: dict = {"chat_id": tg_chat_id}
    if thread_id:
        kw["message_thread_id"] = thread_id

    if name == "telegram_send_file":
        if not url:
            return
        try:
            await bot.send_document(**kw, document=url, caption=caption)
        except Exception:
            await _send(tg_chat_id, bot, f"📎 {caption or 'File'}: {url}", thread_id)

    elif name == "telegram_send_audio":
        if not url:
            return
        try:
            await bot.send_audio(**kw, audio=url, caption=caption)
        except Exception:
            try:
                await bot.send_voice(**kw, voice=url, caption=caption)
            except Exception:
                await _send(tg_chat_id, bot, f"🎵 {caption or 'Audio'}: {url}", thread_id)

    elif name == "telegram_send_photo":
        if not url:
            return
        try:
            await bot.send_photo(**kw, photo=url, caption=caption)
        except Exception:
            await _send(tg_chat_id, bot, f"🖼 {caption or 'Photo'}: {url}", thread_id)

    elif name == "telegram_reply_to":
        msg_id = args.get("message_id")
        if not text:
            return
        try:
            await bot.send_message(
                chat_id=tg_chat_id, text=text,
                reply_to_message_id=int(msg_id) if msg_id else None,
                message_thread_id=thread_id,
            )
        except Exception:
            await _send(tg_chat_id, bot, text, thread_id)

    elif name == "telegram_react":
        msg_id = args.get("message_id")
        emoji  = (args.get("emoji") or "👍").strip()
        if not msg_id:
            return
        try:
            from telegram import ReactionTypeEmoji
            await bot.set_message_reaction(
                chat_id=tg_chat_id, message_id=int(msg_id),
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
        except Exception as exc:
            logger.debug(f"[tg_tools] react failed: {exc}")

    elif name == "telegram_pin_message":
        msg_id = args.get("message_id")
        if not msg_id:
            return
        try:
            await bot.pin_chat_message(
                chat_id=tg_chat_id, message_id=int(msg_id),
                disable_notification=args.get("silent", True),
            )
        except Exception as exc:
            await _err(f"⚠️ Couldn't pin message {msg_id}: {exc}")

    elif name == "telegram_unpin_message":
        msg_id = args.get("message_id")
        try:
            if msg_id:
                await bot.unpin_chat_message(chat_id=tg_chat_id, message_id=int(msg_id))
            else:
                await bot.unpin_all_chat_messages(chat_id=tg_chat_id)
        except Exception as exc:
            logger.warning(f"[tg_tools] unpin failed: {exc}")

    elif name == "telegram_set_chat_title":
        title = (args.get("title") or "").strip()
        if not title:
            return
        try:
            await bot.set_chat_title(chat_id=tg_chat_id, title=title)
        except Exception as exc:
            await _err(f"⚠️ Couldn't set title: {exc}")

    elif name == "telegram_set_chat_description":
        desc = (args.get("description") or "").strip()
        try:
            await bot.set_chat_description(chat_id=tg_chat_id, description=desc)
        except Exception as exc:
            await _err(f"⚠️ Couldn't set description: {exc}")

    elif name == "telegram_create_topic":
        topic_name = (args.get("name") or "").strip()
        if not topic_name:
            return
        try:
            topic = await bot.create_forum_topic(chat_id=tg_chat_id, name=topic_name)
            await _send(
                tg_chat_id, bot,
                f"✅ Topic '{topic_name}' created (thread_id: {topic.message_thread_id})",
                thread_id,
            )
        except Exception as exc:
            await _err(f"⚠️ Couldn't create topic: {exc}")

    elif name == "telegram_edit_topic":
        tid      = args.get("topic_id") or args.get("message_thread_id")
        name_val = (args.get("name") or "").strip()
        if not tid:
            return
        try:
            await bot.edit_forum_topic(
                chat_id=tg_chat_id, message_thread_id=int(tid), name=name_val or None
            )
        except Exception as exc:
            await _err(f"⚠️ Couldn't edit topic: {exc}")

    elif name == "telegram_close_topic":
        tid = args.get("topic_id") or args.get("message_thread_id")
        if not tid:
            return
        try:
            await bot.close_forum_topic(chat_id=tg_chat_id, message_thread_id=int(tid))
        except Exception as exc:
            await _err(f"⚠️ Couldn't close topic: {exc}")

    elif name == "telegram_reopen_topic":
        tid = args.get("topic_id") or args.get("message_thread_id")
        if not tid:
            return
        try:
            await bot.reopen_forum_topic(chat_id=tg_chat_id, message_thread_id=int(tid))
        except Exception as exc:
            await _err(f"⚠️ Couldn't reopen topic: {exc}")

    elif name == "telegram_delete_topic":
        tid = args.get("topic_id") or args.get("message_thread_id")
        if not tid:
            return
        try:
            await bot.delete_forum_topic(chat_id=tg_chat_id, message_thread_id=int(tid))
        except Exception as exc:
            await _err(f"⚠️ Couldn't delete topic: {exc}")
