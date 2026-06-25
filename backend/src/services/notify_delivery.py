"""Out-of-band notification delivery (GitLab #212).

When a notification is created it is pushed over the user's WebSocket immediately.
If the user opted in (User.notify_email / notify_telegram), we ALSO deliver it via
email and/or a Telegram DM so events aren't missed while no client is connected.

Best-effort + fire-and-forget: a delivery failure is logged, never raised, and
never blocks notification creation.
"""
from __future__ import annotations

import logging
from html import escape

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.user import User

logger = logging.getLogger(__name__)


async def deliver_notification(
    user_id: str,
    title: str,
    body: str | None,
    link: str | None,
) -> None:
    """Deliver one notification through the user's enabled out-of-band channels."""
    try:
        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if not user:
                return
            want_email = bool(getattr(user, "notify_email", False)) and bool(user.email)
            want_tg = bool(getattr(user, "notify_telegram", False)) and bool(getattr(user, "telegram_user_id", None))
            if not (want_email or want_tg):
                return
            email = user.email
            tg_chat_id = getattr(user, "telegram_user_id", None)

        if want_email:
            await _send_email(email, title, body, link)
        if want_tg:
            await _send_telegram(tg_chat_id, title, body, link)
    except Exception:  # pragma: no cover - defensive
        logger.exception("[notify_delivery] delivery failed for user %s", user_id)


async def _send_email(to: str, title: str, body: str | None, link: str | None) -> None:
    from src.services.email import send_email
    from src.core.config import get_settings

    app_url = (get_settings().app_url or "").rstrip("/")
    link_html = ""
    if link:
        href = f"{app_url}{link}" if link.startswith("/") else link
        link_html = f'<p><a href="{escape(href)}">Open in Nexora</a></p>'
    html = f"<h2>{escape(title)}</h2>"
    if body:
        html += f"<p>{escape(body)}</p>"
    html += link_html
    text = title + (f"\n\n{body}" if body else "")
    await send_email(to=to, subject=f"[Nexora] {title}", html=html, text=text)


async def _send_telegram(chat_id: str, title: str, body: str | None, link: str | None) -> None:
    """DM the user via the first active Telegram integration's bot token."""
    import httpx
    from src.models.integration import Integration

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Integration).where(
                Integration.integration_type == "telegram",
                Integration.is_active.is_(True),
            )
        )
        token = None
        for integ in rows.scalars().all():
            cfg = integ.get_config() if hasattr(integ, "get_config") else (integ.config or {})
            token = (cfg or {}).get("bot_token") or (cfg or {}).get("token")
            if token:
                break
    if not token:
        return

    msg = f"*{title}*"
    if body:
        msg += f"\n{body}"
    if link:
        msg += f"\n{link}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            )
    except Exception as exc:
        logger.warning("[notify_delivery] telegram send failed: %s", exc)
