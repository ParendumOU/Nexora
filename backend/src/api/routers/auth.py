import uuid
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, EmailStr, field_validator
from src.core.config import get_settings
from src.core.database import get_db
from src.core.rate_limit import rate_limit
from src.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token, _DUMMY_HASH
from src.models.user import User
from src.models.org import Organization, OrgMember, OrgRole
from src.models.signup_invite import SignupInvite
from src.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _fire_audit_event(org_id: str, action: str, resource_type: str,
                       resource_id: str | None = None, user_id: str | None = None) -> None:
    """Fire-and-forget: record an enterprise audit event in the billing worker."""
    from src.core.config import get_settings
    settings = get_settings()
    if not settings.billing_worker_url:
        return
    import threading, urllib.request, json as _json
    def _post() -> None:
        try:
            body = _json.dumps({"org_id": org_id, "action": action, "resource_type": resource_type,
                                 "resource_id": resource_id, "user_id": user_id}).encode()
            req = urllib.request.Request(
                f"{settings.billing_worker_url}/api/metering/audit_event", data=body,
                headers={"Content-Type": "application/json", "X-Internal-Secret": settings.secret_key},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()


def _fire_onboarding(org_id: str, email: str, org_name: str) -> None:
    """Fire-and-forget: notify billing worker to create subscription for new org."""
    from src.core.config import get_settings
    settings = get_settings()
    if not settings.billing_worker_url:
        return
    import threading, urllib.request, json as _json
    secret = settings.secret_key

    def _post() -> None:
        try:
            body = _json.dumps({"org_id": org_id, "email": email, "org_name": org_name}).encode()
            req = urllib.request.Request(
                f"{settings.billing_worker_url}/api/onboarding/new-org",
                data=body,
                headers={"Content-Type": "application/json", "X-Internal-Secret": secret},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # never block registration

    threading.Thread(target=_post, daemon=True).start()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    org_name: str | None = None
    invite_token: str | None = None
    # When set, registration is "invite-first": the new account is created inside the
    # inviting org (no personal org, managed) and this org invite authorizes signup.
    org_invite_token: str | None = None

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        errors = []
        if len(v) < 8:
            errors.append("at least 8 characters")
        if not re.search(r"[A-Z]", v):
            errors.append("one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("one digit")
        if errors:
            raise ValueError("Password must contain: " + ", ".join(errors))
        return v


class CreateSignupInviteRequest(BaseModel):
    email: str | None = None  # optional: lock invite to a specific email address


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TotpChallengeResponse(BaseModel):
    requires_totp: bool = True
    totp_token: str  # short-lived token scoped to 2FA completion only


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:50]


async def _get_active_org_id(user: User, db: AsyncSession) -> str | None:
    if user.active_org_id:
        return user.active_org_id
    result = await db.execute(
        select(OrgMember).where(OrgMember.user_id == user.id).limit(1)
    )
    member = result.scalar_one_or_none()
    if member:
        user.active_org_id = member.org_id
        await db.commit()
        return member.org_id
    return None


@router.get("/first-run")
async def first_run(request: Request, db: AsyncSession = Depends(get_db)):
    """Returns true if no real users exist yet (only the system seed user)."""
    await rate_limit(request, "first-run", max_requests=20, window_seconds=60)
    result = await db.execute(
        select(func.count()).select_from(User).where(User.email != "system@nexora.internal")
    )
    count = result.scalar_one()
    return {"first_run": count == 0}


@router.get("/invite/{token}")
async def validate_signup_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Public — validate a signup invite token before showing the registration form."""
    r = await db.execute(select(SignupInvite).where(SignupInvite.token == token))
    invite = r.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.used_at:
        raise HTTPException(status_code=410, detail="Invite already used")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invite expired")
    return {"valid": True, "email": invite.email, "expires_at": invite.expires_at.isoformat()}


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def create_signup_invite(
    req: CreateSignupInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a platform signup invite link. Superuser only (#162) — a signup invite
    grants access to the whole platform, so a regular user must not mint them."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a superuser can create signup invites")
    invite = SignupInvite(
        id=str(uuid.uuid4()),
        email=req.email or None,
        created_by_id=current_user.id,
    )
    db.add(invite)
    from src.services.audit import record_audit
    await record_audit(db, action="signup_invite.create", user=current_user,
                       resource_type="signup_invite", resource_id=invite.id,
                       detail={"email": req.email or None})
    await db.commit()
    await db.refresh(invite)
    return {
        "token": invite.token,
        "expires_at": invite.expires_at.isoformat(),
        "invite_url": f"/register?invite={invite.token}",
    }


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, "register", max_requests=3, window_seconds=60)

    settings = get_settings()
    invite: SignupInvite | None = None

    # Invite-first registration: an org invite creates a MANAGED account inside the
    # inviting org (no personal org) and authorizes signup on its own, so the platform
    # SignupInvite / REQUIRE_INVITE checks below are skipped when it's present + valid.
    from src.models.org_invite import OrgInvite
    org_invite: OrgInvite | None = None
    if req.org_invite_token:
        oir = await db.execute(select(OrgInvite).where(OrgInvite.token == req.org_invite_token))
        org_invite = oir.scalar_one_or_none()
        if not org_invite:
            raise HTTPException(status_code=403, detail="Invalid or expired invitation")
        if org_invite.accepted_at:
            raise HTTPException(status_code=403, detail="Invitation already used")
        _exp = org_invite.expires_at
        if _exp is not None and _exp.tzinfo is None:
            _exp = _exp.replace(tzinfo=timezone.utc)  # naive rows (SQLite) → assume UTC
        if _exp is not None and _exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Invitation has expired")
        if org_invite.email and org_invite.email.lower() != req.email.lower():
            raise HTTPException(status_code=403, detail="Invitation is not valid for this email address")

    # First-run bypass: if no non-superuser users exist, the invite requirement is
    # waived so the initial admin account can be created via the /setup page.
    # #166: take a transaction-scoped Postgres advisory lock around the count so two
    # concurrent invite-less registrations can't both observe an empty table and both
    # bypass the invite requirement. (No-op on non-PG dialects, e.g. the SQLite tests.)
    is_first_run = False
    if settings.require_invite and not org_invite and not req.invite_token:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            await db.execute(text("SELECT pg_advisory_xact_lock(91823461)"))
        count_r = await db.execute(select(func.count()).select_from(User).where(User.email != "system@nexora.internal"))
        is_first_run = count_r.scalar_one() == 0

    if settings.require_invite and not org_invite and not is_first_run:
        if not req.invite_token:
            raise HTTPException(status_code=403, detail="An invitation is required to register")
        r = await db.execute(select(SignupInvite).where(SignupInvite.token == req.invite_token))
        invite = r.scalar_one_or_none()
        if not invite:
            raise HTTPException(status_code=403, detail="Invalid or expired invitation")
        if invite.used_at:
            raise HTTPException(status_code=403, detail="Invitation already used")
        if invite.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Invitation has expired")
        if invite.email and invite.email.lower() != req.email.lower():
            raise HTTPException(status_code=403, detail="Invitation is not valid for this email address")

    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
    )
    db.add(user)
    await db.flush()

    personal_org: Organization | None = None
    if org_invite:
        # Invite-first → MANAGED account: join the inviting org, no personal org.
        from src.services.billing_limits import enforce_user_quota
        await enforce_user_quota(org_invite.org_id)
        role = OrgRole(org_invite.role) if org_invite.role in OrgRole._value2member_map_ else OrgRole.member
        db.add(OrgMember(id=str(uuid.uuid4()), org_id=org_invite.org_id, user_id=user.id, role=role))
        user.active_org_id = org_invite.org_id
        user.is_managed = True
        org_invite.accepted_at = datetime.now(timezone.utc)
        active_org_id = org_invite.org_id
    else:
        # Normal self-signup → create a personal org owned by the user.
        org_name = req.org_name or f"{req.full_name}'s Workspace"
        base_slug = slugify(org_name)
        slug = base_slug
        i = 1
        while True:
            existing = await db.execute(select(Organization).where(Organization.slug == slug))
            if not existing.scalar_one_or_none():
                break
            slug = f"{base_slug}-{i}"
            i += 1

        personal_org = Organization(id=str(uuid.uuid4()), name=org_name, slug=slug, owner_id=user.id, is_personal=True)
        db.add(personal_org)
        await db.flush()

        db.add(OrgMember(id=str(uuid.uuid4()), org_id=personal_org.id, user_id=user.id, role=OrgRole.owner))
        # Set active org immediately
        user.active_org_id = personal_org.id
        active_org_id = personal_org.id

    if invite:
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by_id = user.id

    # Email verification (graceful no-op when SMTP not configured or feature disabled)
    if settings.require_email_verification and settings.smtp_host:
        import secrets as _secrets
        token = _secrets.token_urlsafe(32)[:64]
        user.verification_token = token
        user.is_verified = False
    else:
        user.is_verified = True

    await db.commit()

    # Send verification email fire-and-forget (only when enabled + SMTP configured)
    if settings.require_email_verification and settings.smtp_host and not user.is_verified:
        import asyncio as _asyncio
        from src.services.email import send_verification_email as _send_verify
        _asyncio.create_task(_send_verify(user.email, user.verification_token))

    # Notify billing worker to create a subscription only for a NEW personal org
    # (a managed account joins an existing org — no new subscription).
    if personal_org is not None:
        _fire_onboarding(personal_org.id, req.email, personal_org.name)

    return TokenResponse(
        access_token=create_access_token(user.id, active_org_id, token_version=user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, "login", max_requests=5, window_seconds=60)
    settings = get_settings()
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    # Always run verify_password to prevent timing-based user enumeration
    candidate_hash = user.hashed_password if user else _DUMMY_HASH
    password_ok = verify_password(req.password, candidate_hash)
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Block login when verification is required, SMTP is configured, and user hasn't verified
    if settings.require_email_verification and settings.smtp_host and not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")

    # If 2FA enabled: issue a short-lived totp_token instead of full JWT
    if user.totp_enabled:
        totp_token = create_access_token(user.id, None, expires_minutes=5, scope="2fa_pending")
        return TotpChallengeResponse(totp_token=totp_token)

    org_id = await _get_active_org_id(user, db)
    if org_id:
        _fire_audit_event(org_id, "user.login", "user", resource_id=user.id, user_id=user.id)
    return TokenResponse(
        access_token=create_access_token(user.id, org_id, token_version=user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


@router.post("/totp-login", response_model=TokenResponse)
async def totp_login(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a totp_token + 6-digit code for a full JWT."""
    import json as _json
    from jose import JWTError
    await rate_limit(request, "totp-login", max_requests=10, window_seconds=60)

    totp_token: str = body.get("totp_token", "")
    code: str = str(body.get("code", "")).strip()

    try:
        payload = decode_token(totp_token)
        if payload.get("scope") != "2fa_pending":
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or not user.totp_enabled:
        raise HTTPException(status_code=401, detail="Invalid token")

    import pyotp, json as _json2
    from src.core.security import decrypt
    secret = decrypt(user.totp_secret)
    totp = pyotp.TOTP(secret)
    verified = totp.verify(code, valid_window=1)

    if not verified and user.totp_backup_codes:
        from src.core.security import encrypt as _encrypt
        codes: list[str] = _json2.loads(decrypt(user.totp_backup_codes))
        if code.upper() in codes:
            verified = True
            codes.remove(code.upper())
            user.totp_backup_codes = _encrypt(_json2.dumps(codes))
            await db.commit()

    if not verified:
        raise HTTPException(status_code=401, detail="Invalid 2FA code")

    org_id = await _get_active_org_id(user, db)
    return TokenResponse(
        access_token=create_access_token(user.id, org_id, token_version=user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, "refresh", max_requests=10, window_seconds=60)
    from jose import JWTError
    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    if payload.get("tv") != user.token_version:
        raise HTTPException(status_code=401, detail="Token has been invalidated")

    org_id = await _get_active_org_id(user, db)

    return TokenResponse(
        access_token=create_access_token(user.id, org_id, token_version=user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


# ── Email verification ────────────────────────────────────────────────────────

@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Validate an email verification token and mark the user as verified."""
    result = await db.execute(select(User).where(User.verification_token == token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    user.is_verified = True
    user.verification_token = None
    await db.commit()
    return {"ok": True, "message": "Email verified successfully"}


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def _validate_pw(cls, v: str) -> str:
        errors = []
        if len(v) < 8:             errors.append("at least 8 characters")
        if not re.search(r"[A-Z]", v): errors.append("one uppercase letter")
        if not re.search(r"[a-z]", v): errors.append("one lowercase letter")
        if not re.search(r"\d", v):    errors.append("one digit")
        if errors:
            raise ValueError("Password must contain: " + ", ".join(errors))
        return v


_RESET_TTL = 3600  # 1 hour


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(req: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Send a password reset link. Always 202 to prevent email enumeration."""
    await rate_limit(request, "forgot-password", max_requests=3, window_seconds=300)

    result = await db.execute(select(User).where(User.email == req.email, User.is_active == True))
    user = result.scalar_one_or_none()

    if user:
        import secrets as _secrets
        from src.core.redis import get_redis
        token = _secrets.token_urlsafe(32)
        redis = get_redis()
        await redis.setex(f"pw_reset:{token}", _RESET_TTL, user.id)
        settings = get_settings()
        reset_url = f"{settings.app_url}/reset-password?token={token}"
        from src.services.email import send_password_reset
        await send_password_reset(user.email, user.full_name, reset_url)

    return {"detail": "If that email is registered you will receive a reset link shortly."}


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(req: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Validate reset token and update password. Issues new tokens on success."""
    await rate_limit(request, "reset-password", max_requests=5, window_seconds=60)

    from src.core.redis import get_redis
    redis = get_redis()
    key = f"pw_reset:{req.token}"
    user_id_raw = await redis.get(key)
    if not user_id_raw:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    uid = user_id_raw.decode() if isinstance(user_id_raw, bytes) else user_id_raw
    result = await db.execute(select(User).where(User.id == uid, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user.hashed_password = hash_password(req.password)
    user.token_version += 1  # invalidate all existing sessions
    await db.commit()
    await redis.delete(key)

    org_id = await _get_active_org_id(user, db)
    return TokenResponse(
        access_token=create_access_token(user.id, org_id, token_version=user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )
