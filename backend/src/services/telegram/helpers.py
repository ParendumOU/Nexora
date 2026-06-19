"""Telegram bot — shared constants, regexes, and text-sending helpers."""
from __future__ import annotations

import asyncio
import logging
import re

from telegram.error import BadRequest, TelegramError
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"

_LOCK_TTL    = 30
_MAX_TG_LEN  = 4096
_HISTORY_MAX = 80
_HIST_PAGE_SIZE = 5

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".sql", ".xml", ".log", ".gitignore", ".dockerfile", ".makefile",
    ".c", ".cpp", ".h", ".hpp", ".java", ".go", ".rs", ".rb", ".php",
    ".tf", ".hcl",
}

_WHISPER_PROVIDERS = ("openai", "groq")
_VISION_PROVIDERS  = ("anthropic", "openai")

UPLOADS_DIR = "/app/uploads"

# ── Regexes ───────────────────────────────────────────────────────────────────

_TOOL_FENCE_RE  = re.compile(r'```tool_calls\s*\n([\s\S]*?)\n?```', re.IGNORECASE)
_JUNK_ONLY_RE   = re.compile(r'^[-=_*]{2,}$')
_MD_HEADER_RE   = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_FINAL_TAG_RE   = re.compile(r'<\s*final\s*/?\s*>|<\s*final\s*>\s*<\s*/\s*final\s*>', re.IGNORECASE)


# ── Text helpers ──────────────────────────────────────────────────────────────

def _sanitize_for_telegram(text: str) -> str:
    """Strip Markdown header markers (##) and turn-end markers that Telegram's parser treats as literals."""
    text = _FINAL_TAG_RE.sub('', text)
    return _MD_HEADER_RE.sub('', text)


def _is_sendable(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return not all(_JUNK_ONLY_RE.match(line) for line in stripped.splitlines() if line.strip())


def _chunk_text(text: str) -> list[str]:
    if len(text) <= _MAX_TG_LEN:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= _MAX_TG_LEN:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, _MAX_TG_LEN)
        if cut <= 0:
            cut = _MAX_TG_LEN
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def _send(tg_chat_id: int, bot, text: str, thread_id: int | None = None) -> None:
    kw: dict = {"chat_id": tg_chat_id}
    if thread_id:
        kw["message_thread_id"] = thread_id
    for chunk in _chunk_text(text):
        try:
            await bot.send_message(**kw, text=chunk, parse_mode=ParseMode.MARKDOWN)
        except (BadRequest, TelegramError):
            try:
                await bot.send_message(**kw, text=chunk)
            except Exception as exc:
                logger.warning(f"[tg] send failed: {exc}")


async def _send_first(
    tg_chat_id: int, bot, text: str, thread_id: int | None = None
) -> int | None:
    """Send a single message and return its message_id, or None on failure."""
    kw: dict = {"chat_id": tg_chat_id}
    if thread_id:
        kw["message_thread_id"] = thread_id
    chunk = _chunk_text(text)[0]
    try:
        msg = await bot.send_message(**kw, text=chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        return msg.message_id
    except (BadRequest, TelegramError):
        try:
            msg = await bot.send_message(**kw, text=chunk, disable_web_page_preview=True)
            return msg.message_id
        except Exception as exc:
            logger.warning(f"[tg] send_first failed: {exc}")
            return None


async def _edit_silent(tg_chat_id: int, bot, message_id: int, text: str) -> None:
    """Edit a message in-place; silently swallows 'not modified' and other errors."""
    kw: dict = {"chat_id": tg_chat_id, "message_id": message_id}
    chunk = _chunk_text(text)[0]
    try:
        await bot.edit_message_text(**kw, text=chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except (BadRequest, TelegramError) as exc:
        if "message is not modified" in str(exc).lower():
            return
        try:
            await bot.edit_message_text(**kw, text=chunk, disable_web_page_preview=True)
        except Exception as exc2:
            logger.warning(f"[tg] edit failed: {exc2}")
    except Exception as exc:
        logger.warning(f"[tg] edit failed: {exc}")


async def _delete_silent(tg_chat_id: int, bot, message_id: int) -> None:
    """Delete a message, ignoring all errors."""
    try:
        await bot.delete_message(chat_id=tg_chat_id, message_id=message_id)
    except Exception as exc:
        logger.warning(f"[tg] delete failed: {exc}")


async def _send_blockquote(
    tg_chat_id: int, bot, text: str, thread_id: int | None = None
) -> None:
    """Send a short HTML blockquote message (used for metadata footer)."""
    import html as _html
    kw: dict = {"chat_id": tg_chat_id}
    if thread_id:
        kw["message_thread_id"] = thread_id
    try:
        await bot.send_message(
            **kw,
            text=f"<blockquote>{_html.escape(text)}</blockquote>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning(f"[tg] blockquote send failed: {exc}")


async def _send_blockquote_returning_id(
    tg_chat_id: int, bot, text: str, thread_id: int | None = None
) -> int | None:
    """Send an HTML blockquote message and return its message_id, or None on failure."""
    import html as _html
    kw: dict = {"chat_id": tg_chat_id}
    if thread_id:
        kw["message_thread_id"] = thread_id
    try:
        msg = await bot.send_message(
            **kw,
            text=f"<blockquote>{_html.escape(text)}</blockquote>",
            parse_mode="HTML",
        )
        return msg.message_id
    except Exception as exc:
        logger.warning(f"[tg] blockquote send failed: {exc}")
        return None


async def _keep_typing(
    bot, tg_chat_id: int, stop_event: asyncio.Event, thread_id: int | None = None
) -> None:
    kw: dict = {"chat_id": tg_chat_id, "action": "typing"}
    if thread_id:
        kw["message_thread_id"] = thread_id
    try:
        while True:
            try:
                await bot.send_chat_action(**kw)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4.0)
                return
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        pass
