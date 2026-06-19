"""Telegram bot — media download, transcription, OCR, and file extraction."""
from __future__ import annotations

import logging

from telegram import Message as TgMessage  # type used in _process_message signature

from src.services.telegram.helpers import (
    _send, _TEXT_EXTENSIONS, UPLOADS_DIR, _WHISPER_PROVIDERS, _VISION_PROVIDERS,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB per file


# ── Upload storage ────────────────────────────────────────────────────────────

def _save_upload(vchat_id: str, filename: str, data: bytes) -> str:
    """Save file to UPLOADS_DIR/{vchat_id}/ and return the full path."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File too large: {len(data)} bytes (max {MAX_UPLOAD_BYTES})")
    import os
    dest_dir = os.path.join(UPLOADS_DIR, vchat_id)
    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(filename) or "file"
    dest = os.path.join(dest_dir, safe_name)
    if os.path.exists(dest):
        base, ext2 = os.path.splitext(safe_name)
        i = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{base}_{i}{ext2}")
            i += 1
    with open(dest, "wb") as f:
        f.write(data)
    return dest


# ── Provider lookup ───────────────────────────────────────────────────────────

async def _find_media_provider(
    org_id: str, provider_types: tuple[str, ...]
) -> "tuple[str, str | None, str] | None":
    """Return (api_key, base_url, provider_type) for the first active matching provider."""
    from src.models.provider import Provider
    from src.providers.router import _get_credentials
    from src.core.database import AsyncSessionLocal
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Provider).where(
                Provider.org_id == org_id,
                Provider.provider_type.in_(provider_types),
                Provider.is_active == True,
            ).order_by(Provider.priority.desc())
        )
        for p in r.scalars().all():
            creds = _get_credentials(p)
            api_key = creds.get("api_key") or creds.get("token") or ""
            if api_key:
                return api_key, p.base_url, p.provider_type
    return None


# ── Transcription ─────────────────────────────────────────────────────────────

async def _transcribe_audio_bytes(audio_bytes: bytes, filename: str, org_id: str) -> str | None:
    found = await _find_media_provider(org_id, _WHISPER_PROVIDERS)
    if not found:
        return None
    api_key, base_url, ptype = found
    try:
        import io
        import openai
        kw: dict = {"api_key": api_key}
        if base_url:
            kw["base_url"] = base_url
        client = openai.AsyncOpenAI(**kw)
        model = "whisper-large-v3" if ptype == "groq" else "whisper-1"
        result = await client.audio.transcriptions.create(
            model=model,
            file=(filename, io.BytesIO(audio_bytes), "audio/ogg"),
        )
        return result.text or None
    except Exception as exc:
        logger.warning(f"[tg_media] transcription failed ({ptype}): {exc}")
        return None


# ── Vision ────────────────────────────────────────────────────────────────────

async def _describe_image_bytes(image_bytes: bytes, mime_type: str, org_id: str) -> str | None:
    import base64
    b64 = base64.standard_b64encode(image_bytes).decode()
    prompt = "Describe what you see in this image concisely."

    found = await _find_media_provider(org_id, ("anthropic",))
    if found:
        api_key, base_url, _ = found
        try:
            import anthropic as ant
            kw: dict = {"api_key": api_key}
            if base_url:
                kw["base_url"] = base_url
            client = ant.AsyncAnthropic(**kw)
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            if resp.content:
                return resp.content[0].text
        except Exception as exc:
            logger.warning(f"[tg_media] Anthropic vision failed: {exc}")

    found = await _find_media_provider(org_id, ("openai",))
    if found:
        api_key, base_url, _ = found
        try:
            import openai
            kw = {"api_key": api_key}
            if base_url:
                kw["base_url"] = base_url
            client = openai.AsyncOpenAI(**kw)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=512,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            if resp.choices:
                return resp.choices[0].message.content
        except Exception as exc:
            logger.warning(f"[tg_media] OpenAI vision failed: {exc}")

    return None


# ── Document extraction ───────────────────────────────────────────────────────

def _extract_document_text(data: bytes, filename: str) -> str | None:
    """Extract readable text from a file. Returns None for unsupported binary formats."""
    import os
    import io
    ext = os.path.splitext(filename.lower())[1]

    if ext in _TEXT_EXTENSIONS:
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return None

    if ext == ".pdf":
        try:
            import pdfplumber
            text_parts: list[str] = []
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n\n".join(text_parts) or None
        except Exception as exc:
            logger.warning(f"[tg_media] PDF extraction failed for {filename}: {exc}")
            return None

    if ext in (".docx",):
        try:
            import docx
            import io as _io
            doc = docx.Document(_io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip()) or None
        except Exception as exc:
            logger.warning(f"[tg_media] DOCX extraction failed for {filename}: {exc}")
            return None

    return None


def _list_archive_contents(data: bytes, filename: str) -> str | None:
    """Return a newline-joined list of archive members, or None if not a recognised archive."""
    import os
    import io
    ext = os.path.splitext(filename.lower())[1]

    if ext == ".zip" or filename.lower().endswith(".zip"):
        try:
            import zipfile
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            return "\n".join(names[:200]) + ("\n..." if len(names) > 200 else "")
        except Exception:
            return None

    if ext in (".tar", ".gz", ".bz2", ".xz") or any(
        filename.lower().endswith(s) for s in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")
    ):
        try:
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                names = tf.getnames()
            return "\n".join(names[:200]) + ("\n..." if len(names) > 200 else "")
        except Exception:
            return None

    return None


# ── Message processor ─────────────────────────────────────────────────────────

async def _process_message(
    msg: TgMessage, bot, org_id: str, bot_username: str | None, vchat_id: str
) -> str | None:
    """Download and process all content in a Telegram message into a text string for the LLM."""
    parts: list[str] = []

    text    = (msg.text    or "").strip()
    caption = (msg.caption or "").strip()
    if bot_username:
        mention = f"@{bot_username}"
        text    = text.replace(mention, "").strip()
        caption = caption.replace(mention, "").strip()

    if text:
        parts.append(text)

    if msg.voice:
        try:
            if (msg.voice.file_size or 0) > MAX_UPLOAD_BYTES:
                raise ValueError(f"Voice too large: {msg.voice.file_size} bytes")
            tg_file    = await bot.get_file(msg.voice.file_id)
            audio_data = bytes(await tg_file.download_as_bytearray())
            saved_path = _save_upload(vchat_id, "voice.ogg", audio_data)
            transcript = await _transcribe_audio_bytes(audio_data, "voice.ogg", org_id)
            if transcript:
                parts.append(f"[Voice message transcription]: {transcript}")
            else:
                parts.append(
                    f"[Voice message saved: {saved_path}]\n"
                    "(No STT provider configured — raw audio file available at the path above)"
                )
        except Exception as exc:
            logger.warning(f"[tg_media] voice download failed: {exc}")
            parts.append("[Voice message — download failed]")

    if msg.audio:
        fname = msg.audio.file_name or msg.audio.title or "audio.mp3"
        try:
            if (msg.audio.file_size or 0) > MAX_UPLOAD_BYTES:
                raise ValueError(f"Audio too large: {msg.audio.file_size} bytes")
            tg_file    = await bot.get_file(msg.audio.file_id)
            audio_data = bytes(await tg_file.download_as_bytearray())
            saved_path = _save_upload(vchat_id, fname, audio_data)
            transcript = await _transcribe_audio_bytes(audio_data, fname, org_id)
            if transcript:
                parts.append(
                    f"[Audio file saved: {saved_path}]\n"
                    f"[Transcription]: {transcript}"
                )
            else:
                parts.append(f"[Audio file saved: {saved_path}] (could not transcribe)")
        except Exception as exc:
            logger.warning(f"[tg_media] audio download failed: {exc}")
            parts.append(f"[Audio: {fname} — download failed]")

    if msg.photo:
        photo = msg.photo[-1]
        try:
            if (photo.file_size or 0) > MAX_UPLOAD_BYTES:
                raise ValueError(f"Photo too large: {photo.file_size} bytes")
            tg_file  = await bot.get_file(photo.file_id)
            img_data = bytes(await tg_file.download_as_bytearray())
            saved_path = _save_upload(vchat_id, f"photo_{photo.file_unique_id}.jpg", img_data)
            desc = await _describe_image_bytes(img_data, "image/jpeg", org_id)
            cap_part = f"\nCaption: {caption}" if caption else ""
            parts.append(
                f"[Photo saved: {saved_path}]\n"
                f"[Description]: {desc or 'no description available'}{cap_part}"
            )
        except Exception as exc:
            logger.warning(f"[tg_media] photo download failed: {exc}")
            parts.append(f"[Image{' — ' + caption if caption else ''}]")

    if msg.document:
        fname    = msg.document.file_name or "file"
        mime     = msg.document.mime_type or ""
        try:
            if (msg.document.file_size or 0) > MAX_UPLOAD_BYTES:
                raise ValueError(f"Document too large: {msg.document.file_size} bytes")
            tg_file  = await bot.get_file(msg.document.file_id)
            doc_data = bytes(await tg_file.download_as_bytearray())
            saved_path = _save_upload(vchat_id, fname, doc_data)
            cap_part = f"\nCaption: {caption}" if caption else ""

            extracted = _extract_document_text(doc_data, fname)
            if extracted:
                if len(extracted) > 12000:
                    trunc_note = f"\n... [truncated — {len(extracted)} chars total, full file at path above]"
                    extracted = extracted[:12000] + trunc_note
                parts.append(
                    f"[File saved: {saved_path}]{cap_part}\n"
                    f"[Extracted content]:\n{extracted}"
                )
            elif archive_listing := _list_archive_contents(doc_data, fname):
                parts.append(
                    f"[Archive saved: {saved_path}]{cap_part}\n"
                    f"[Contents]:\n{archive_listing}"
                )
            elif mime.startswith("image/"):
                desc = await _describe_image_bytes(doc_data, mime, org_id)
                parts.append(
                    f"[Image file saved: {saved_path}]{cap_part}\n"
                    f"[Description]: {desc or 'no description available'}"
                )
            else:
                parts.append(
                    f"[File saved: {saved_path}] (type: {mime or 'unknown'}){cap_part}\n"
                    "The agent can read, analyse or process this file using available tools."
                )
        except Exception as exc:
            logger.warning(f"[tg_media] document download failed: {exc}")
            parts.append(f"[File: {fname} — download failed]")
    elif caption and not msg.photo:
        parts.append(caption)

    if msg.video:
        fname = msg.video.file_name or "video.mp4"
        try:
            if (msg.video.file_size or 0) > MAX_UPLOAD_BYTES:
                raise ValueError(f"Video too large: {msg.video.file_size} bytes")
            tg_file   = await bot.get_file(msg.video.file_id)
            vid_data  = bytes(await tg_file.download_as_bytearray())
            saved_path = _save_upload(vchat_id, fname, vid_data)
            cap_part  = f"\nCaption: {caption}" if caption else ""
            parts.append(f"[Video saved: {saved_path}]{cap_part}")
        except Exception as exc:
            logger.warning(f"[tg_media] video download failed: {exc}")
            parts.append(f"[Video{' — ' + caption if caption else ''}]")

    if msg.video_note:
        parts.append("[Video note]")
    if msg.sticker:
        parts.append(f"[Sticker {msg.sticker.emoji or ''}]".strip())
    if msg.location:
        parts.append(f"[Location: lat={msg.location.latitude}, lon={msg.location.longitude}]")
    if msg.contact:
        c = msg.contact
        parts.append(f"[Contact: {c.first_name} {c.last_name or ''} {c.phone_number}]".strip())

    return "\n".join(parts) if parts else None
