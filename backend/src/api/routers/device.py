"""Mobile device pairing.

Flow:
  1. Web app (authenticated user) → POST /auth/device/start
       → mints a short-lived pairing code in Redis (TTL 5 min) bound to {user_id, org_id}.
       The web UI renders a QR encoding {"url": <server base url>, "code": <code>}.
  2. Mobile app scans the QR → POST /auth/device/pair {code, device_name, platform}
       → creates a DeviceToken row, returns a long-lived device secret (nxd_...) plus a
       fresh access JWT. The pairing code is consumed (single use).
  3. Mobile stores the nxd_ secret in secure storage and calls POST /auth/device/refresh
       whenever its access JWT expires to obtain a new one.

The access JWT is a standard {sub, org, type:access} token, so all existing REST and
WebSocket auth paths accept it with zero changes. The nxd_ secret is per-device and
individually revocable (GET/DELETE /auth/device) without bumping the user's global
token_version (which would log out web/CLI sessions).
"""
import base64
import hashlib
import io
import json
import secrets
from datetime import datetime, timezone

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.config import get_settings
from src.core.database import get_db
from src.core.rate_limit import rate_limit
from src.core.redis import get_redis
from src.core.security import create_access_token
from src.models.device_token import DeviceToken
from src.models.user import User

router = APIRouter(prefix="/auth/device", tags=["device"])

_PREFIX = "nxd_"
_CODE_TTL = 300  # pairing code lifetime, seconds
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I
_CODE_LEN = 8
_MAX_DEVICES = 10


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def _qr_b64(payload: str) -> str:
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _resolve_base_url(override: str | None, request: Request) -> str:
    """The server URL the mobile app will hit. Prefer the caller-supplied origin
    (the web app's window.location.origin — most accurate behind a reverse proxy),
    then the configured app_url, then the request base URL as a last resort."""
    candidate = (override or "").strip() or get_settings().app_url or str(request.base_url)
    return candidate.rstrip("/")


# ── schemas ─────────────────────────────────────────────────────────────────

class DeviceStartRequest(BaseModel):
    base_url: str | None = None  # optional: web sends window.location.origin


class DeviceStartResponse(BaseModel):
    code: str
    expires_in: int
    url: str
    qr_b64: str  # base64 PNG of {"url","code"} — render directly as <img src="data:image/png;base64,...">.


class DevicePairRequest(BaseModel):
    code: str
    device_name: str | None = None
    platform: str | None = None  # ios / android


class DevicePairResponse(BaseModel):
    access_token: str
    device_token: str
    device_id: str
    org_id: str | None
    user_name: str
    user_email: str


class DeviceRefreshRequest(BaseModel):
    device_token: str


class AccessTokenResponse(BaseModel):
    access_token: str


class DeviceResponse(BaseModel):
    id: str
    name: str
    platform: str
    created_at: datetime
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("/start", response_model=DeviceStartResponse)
async def device_start(
    request: Request,
    body: DeviceStartRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated web user: generate a one-time pairing code + QR for the mobile app."""
    await rate_limit(request, "device-start", max_requests=10, window_seconds=60)
    org_id = await get_active_org_id(current_user, db)
    base_url = _resolve_base_url(body.base_url if body else None, request)

    redis = get_redis()
    # Retry a few times in the (vanishingly unlikely) event of a code collision.
    for _ in range(5):
        code = _gen_code()
        key = f"device_pair:{code}"
        ok = await redis.set(
            key,
            json.dumps({"user_id": current_user.id, "org_id": org_id}),
            ex=_CODE_TTL,
            nx=True,
        )
        if ok:
            qr_payload = json.dumps({"url": base_url, "code": code})
            return DeviceStartResponse(
                code=code, expires_in=_CODE_TTL, url=base_url, qr_b64=_qr_b64(qr_payload)
            )
    raise HTTPException(status_code=503, detail="Could not allocate pairing code, retry")


@router.post("/pair", response_model=DevicePairResponse)
async def device_pair(
    req: DevicePairRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Mobile device: exchange a scanned pairing code for a device token + access JWT."""
    await rate_limit(request, "device-pair", max_requests=10, window_seconds=60)

    redis = get_redis()
    code = (req.code or "").strip().upper()
    key = f"device_pair:{code}"
    raw = await redis.get(key)
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing code")
    # Consume immediately (single use) to prevent races / replay.
    await redis.delete(key)

    data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    user_id = data["user_id"]
    org_id = data.get("org_id")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User no longer active")

    # Enforce a per-user device cap (counting only live devices).
    existing = await db.execute(
        select(DeviceToken).where(
            DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None)
        )
    )
    if len(existing.scalars().all()) >= _MAX_DEVICES:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_DEVICES} paired devices reached")

    raw_token = _PREFIX + secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    platform = (req.platform or "unknown").lower()
    if platform not in ("ios", "android", "unknown"):
        platform = "unknown"

    device = DeviceToken(
        user_id=user_id,
        org_id=org_id,
        name=(req.device_name or "Mobile device").strip()[:100] or "Mobile device",
        platform=platform,
        token_hash=token_hash,
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    return DevicePairResponse(
        access_token=create_access_token(user.id, org_id),
        device_token=raw_token,
        device_id=device.id,
        org_id=org_id,
        user_name=user.full_name or user.email,
        user_email=user.email,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def device_refresh(
    req: DeviceRefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Mobile device: swap the long-lived nxd_ secret for a fresh access JWT."""
    await rate_limit(request, "device-refresh", max_requests=30, window_seconds=60)

    token = (req.device_token or "").strip()
    if not token.startswith(_PREFIX):
        raise HTTPException(status_code=401, detail="Invalid device token")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(select(DeviceToken).where(DeviceToken.token_hash == token_hash))
    device = result.scalar_one_or_none()
    if not device or device.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Device not paired or revoked")

    user_result = await db.execute(select(User).where(User.id == device.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User no longer active")

    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()

    return AccessTokenResponse(access_token=create_access_token(user.id, device.org_id))


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's live (non-revoked) paired devices."""
    result = await db.execute(
        select(DeviceToken)
        .where(DeviceToken.user_id == current_user.id, DeviceToken.revoked_at.is_(None))
        .order_by(DeviceToken.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{device_id}", status_code=204)
async def revoke_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a paired device. Its access JWTs expire within minutes; refresh is blocked immediately."""
    result = await db.execute(
        select(DeviceToken).where(
            DeviceToken.id == device_id, DeviceToken.user_id == current_user.id
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.revoked_at = datetime.now(timezone.utc)
    await db.commit()
