"""TOTP 2FA endpoints — setup, verify, disable, backup codes."""
import base64
import io
import json
import secrets
import string

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.core.security import encrypt, decrypt
from src.models.user import User

router = APIRouter(prefix="/users/me/totp", tags=["totp"])

APP_NAME = "Nexora"
BACKUP_CODE_COUNT = 8
BACKUP_CODE_LENGTH = 8
TOTP_WINDOW = 1  # ±1 interval tolerance


def _gen_backup_codes() -> list[str]:
    alphabet = string.ascii_uppercase + string.digits
    return ["".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH)) for _ in range(BACKUP_CODE_COUNT)]


def _qr_b64(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class VerifyRequest(BaseModel):
    code: str


class DisableRequest(BaseModel):
    code: str  # must supply current TOTP or a backup code to disable


@router.post("/setup")
async def setup_totp(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new TOTP secret. Does NOT enable 2FA yet — user must verify first."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=current_user.email, issuer_name=APP_NAME)

    # Store encrypted secret (not yet active — totp_enabled stays False until verify)
    current_user.totp_secret = encrypt(secret)
    current_user.totp_enabled = False
    await db.commit()

    backup_codes = _gen_backup_codes()
    return {
        "secret": secret,
        "qr_code_b64": _qr_b64(uri),
        "backup_codes": backup_codes,  # shown once — user must save these
        "otpauth_uri": uri,
    }


@router.post("/verify-setup")
async def verify_setup(
    req: VerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm first TOTP code to activate 2FA. Stores encrypted backup codes."""
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Run /setup first")
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA already enabled")

    secret = decrypt(current_user.totp_secret)
    totp = pyotp.TOTP(secret)
    if not totp.verify(req.code.strip(), valid_window=TOTP_WINDOW):
        raise HTTPException(status_code=400, detail="Invalid code")

    backup_codes = _gen_backup_codes()
    current_user.totp_enabled = True
    current_user.totp_backup_codes = encrypt(json.dumps(backup_codes))
    await db.commit()

    return {"enabled": True, "backup_codes": backup_codes}


@router.post("/disable")
async def disable_totp(
    req: DisableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable 2FA. Requires current TOTP code or a valid backup code."""
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    secret = decrypt(current_user.totp_secret)
    totp = pyotp.TOTP(secret)
    code = req.code.strip()
    verified = totp.verify(code, valid_window=TOTP_WINDOW)

    if not verified:
        # Try backup code
        if current_user.totp_backup_codes:
            codes: list[str] = json.loads(decrypt(current_user.totp_backup_codes))
            if code.upper() in codes:
                verified = True
                codes.remove(code.upper())
                current_user.totp_backup_codes = encrypt(json.dumps(codes))

    if not verified:
        raise HTTPException(status_code=400, detail="Invalid code")

    current_user.totp_secret = None
    current_user.totp_enabled = False
    current_user.totp_backup_codes = None
    await db.commit()
    return {"enabled": False}


@router.get("/status")
async def totp_status(current_user: User = Depends(get_current_user)):
    """Return current 2FA state for the settings UI."""
    return {"enabled": current_user.totp_enabled}
