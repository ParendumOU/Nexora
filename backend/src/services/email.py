"""Async email service using aiosmtplib.

If SMTP_HOST is not configured, emails are logged at INFO level instead of
being sent — safe for development and self-hosted instances without SMTP.
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    """Send an email. Returns True on success, False on failure (never raises)."""
    from src.core.config import get_settings
    settings = get_settings()

    if not settings.smtp_host:
        logger.info("[email] SMTP not configured — would send to %s: %s", to, subject)
        return False

    try:
        import aiosmtplib
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        if text:
            msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_port == 587,
        )
        logger.info("[email] Sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        logger.error("[email] Failed to send to %s: %s", to, exc)
        return False


async def send_verification_email(to: str, token: str) -> bool:
    from src.core.config import get_settings
    settings = get_settings()
    url = f"{settings.app_url}/verify-email?token={token}"
    subject = "Verify your Nexora account"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
      <h2 style="font-size:20px;font-weight:600;margin-bottom:8px">Verify your email</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Welcome to Nexora! Click the button below to verify your email address.
        This link expires in 24 hours.
      </p>
      <a href="{url}"
         style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;
                padding:12px 24px;border-radius:8px;font-weight:600;font-size:14px">
        Verify email
      </a>
      <p style="color:#9ca3af;font-size:12px;margin-top:24px">
        If you didn't create a Nexora account, you can safely ignore this email.
      </p>
    </div>
    """
    text = f"Verify your Nexora account: {url}\n\nLink expires in 24 hours."
    return await send_email(to, subject, html, text)


async def send_password_reset(to: str, full_name: str, reset_url: str) -> bool:
    subject = "Reset your Nexora password"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
      <h2 style="font-size:20px;font-weight:600;margin-bottom:8px">Reset your password</h2>
      <p style="color:#6b7280;margin-bottom:24px">
        Hi {full_name},<br>we received a request to reset your Nexora password.
        Click the button below to choose a new one. This link expires in 1 hour.
      </p>
      <a href="{reset_url}"
         style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;
                padding:12px 24px;border-radius:8px;font-weight:600;font-size:14px">
        Reset password
      </a>
      <p style="color:#9ca3af;font-size:12px;margin-top:24px">
        If you didn't request this, ignore this email — your password won't change.
      </p>
    </div>
    """
    text = f"Reset your Nexora password: {reset_url}\n\nLink expires in 1 hour."
    return await send_email(to, subject, html, text)
