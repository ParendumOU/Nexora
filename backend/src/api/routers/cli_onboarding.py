"""Zero-touch CLI onboarding.

An org admin creates an OrgInvite bound to a person's email (see orgs.create_invite),
then shares a single one-liner. The employee pastes it into a terminal; the installer
downloads the `nexora` binary and calls `nexora join`, which hits `POST /auth/cli/redeem`
here. That endpoint, in one shot:

  1. Resolves (or auto-creates, passwordless) the account for the invite's email.
  2. Adds it to the inviting org (honoring the per-license user quota).
  3. Mints a user-level nxr_ API key + an nxd_ device token (so the CLI shows up in
     Settings -> Devices and is individually revocable).
  4. Consumes the invite (single use).

The invite token is a bearer credential (like every other invite link): whoever holds
it joins as the bound email. It is single-use and expiring; bind it to the real person's
email so a leaked link can't be reused after the intended employee redeems it.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import get_db
from src.core.rate_limit import rate_limit
from src.core.security import create_access_token, hash_password
from src.models.device_token import DeviceToken
from src.models.org import Organization, OrgMember, OrgRole
from src.models.org_invite import OrgInvite
from src.models.user import User
from src.models.user_api_key import UserApiKey

router = APIRouter(prefix="/auth/cli", tags=["cli-onboarding"])

# Public installer scripts (GitHub Releases host the binaries). The one-liner passes
# the instance URL + invite token as script args; the installer runs `nexora join`.
_CLI_REPO_RAW = "https://raw.githubusercontent.com/ParendumOU/Nexora-CLI/main"
_MAX_DEVICES = 10
_MAX_KEYS = 20


_DEFAULT_APP_URL = "http://localhost:3000"


def resolve_instance_base_url(request: Request) -> str:
    """The externally reachable base URL of THIS instance — what the employee's CLI
    will connect to over REST + WS (the nginx/public origin, not frontend:3000).

    Auto-derived from the incoming request so it tracks whatever host + scheme the
    admin is actually reaching the instance at — LAN IP, domain, http or https —
    honoring the reverse proxy in front of us (X-Forwarded-Proto / X-Forwarded-Host).
    An explicitly configured APP_URL (anything other than the localhost default)
    always wins, for deployments whose public API origin differs from the web UI."""
    # 1. Explicit override wins — admin set APP_URL to the real public origin.
    configured = (get_settings().app_url or "").strip().rstrip("/")
    if configured and configured != _DEFAULT_APP_URL:
        return configured

    # 2. Derive from the request, honoring the reverse proxy (nginx forwards Host +
    #    X-Forwarded-Proto; an outer TLS terminator sets X-Forwarded-Host/Proto).
    h = request.headers
    proto = (h.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = (
        h.get("x-forwarded-host") or h.get("host") or request.url.netloc
    ).split(",")[0].strip()
    if host:
        return f"{proto}://{host}"

    # 3. Last resort (e.g. non-HTTP context with no headers).
    return configured or _DEFAULT_APP_URL


def build_cli_install_commands(base_url: str, token: str) -> dict[str, str]:
    """The copy-paste one-liners an admin hands to an employee."""
    return {
        "cli_install_sh": (
            f"curl -fsSL {_CLI_REPO_RAW}/install.sh | bash -s -- "
            f"--join {token} --url {base_url}"
        ),
        "cli_install_ps": (
            f"& ([scriptblock]::Create((irm {_CLI_REPO_RAW}/install.ps1))) "
            f"-Join {token} -Url {base_url}"
        ),
    }


# ── schemas ───────────────────────────────────────────────────────────────────

class CliRedeemRequest(BaseModel):
    token: str
    device_name: str | None = None
    platform: str | None = None  # linux / darwin / windows


class CliRedeemResponse(BaseModel):
    access_token: str
    device_token: str
    api_key: str
    org_id: str
    org_name: str
    user_email: str
    user_name: str
    created_account: bool


# ── endpoints ──────────────────────────────────────────────────────────────────

def _load_valid_invite_stmt(token: str):
    return select(OrgInvite).where(OrgInvite.token == token.strip())


def _validate_invite(invite: OrgInvite | None) -> OrgInvite:
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at:
        raise HTTPException(status_code=410, detail="Invite already used")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invite expired")
    if not invite.email:
        raise HTTPException(
            status_code=400,
            detail="This invite is not enabled for CLI onboarding (no email bound). "
                   "Ask your admin for a terminal invite.",
        )
    return invite


@router.get("/invite/{token}")
async def cli_invite_details(token: str, db: AsyncSession = Depends(get_db)):
    """Public — preview a CLI invite before redeeming (the CLI shows this)."""
    r = await db.execute(_load_valid_invite_stmt(token))
    invite = _validate_invite(r.scalar_one_or_none())

    org_r = await db.execute(select(Organization).where(Organization.id == invite.org_id))
    org = org_r.scalar_one_or_none()
    ur = await db.execute(select(User).where(func.lower(User.email) == invite.email.lower()))
    exists = ur.scalar_one_or_none() is not None

    return {
        "org_id": invite.org_id,
        "org_name": org.name if org else "Unknown",
        "email": invite.email,
        "full_name": invite.full_name,
        "role": invite.role,
        "user_exists": exists,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.post("/redeem", response_model=CliRedeemResponse)
async def cli_redeem(
    req: CliRedeemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Redeem a CLI invite: resolve/auto-create the account, join the org, and hand
    back an access JWT + device token + API key. No prior authentication required —
    the invite token IS the credential."""
    await rate_limit(request, "cli-redeem", max_requests=10, window_seconds=60)

    r = await db.execute(_load_valid_invite_stmt(req.token))
    invite = _validate_invite(r.scalar_one_or_none())

    # ── resolve or create the user ──────────────────────────────────────────────
    ur = await db.execute(select(User).where(func.lower(User.email) == invite.email.lower()))
    user = ur.scalar_one_or_none()
    created = False
    if user is None:
        created = True
        display = (invite.full_name or "").strip() or invite.email.split("@")[0]
        user = User(
            id=str(uuid.uuid4()),
            email=invite.email,
            # Passwordless: a random unguessable hash. The employee can set a real
            # password later from Settings (or via forgot-password) if they want web
            # login; the CLI authenticates via the device token + API key below.
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=display,
            is_verified=True,
            # Born from an org invite → managed: no personal org, tied to this one org.
            is_managed=True,
            # Passwordless: the random hash above is unguessable. The employee can set a
            # real password later (POST /users/me/password) to also sign in on the web.
            has_password=False,
        )
        db.add(user)
        await db.flush()
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")
    elif getattr(user, "is_managed", False):
        # A managed account is tied to exactly one org — only re-redeeming an invite
        # for that same org is allowed (to re-pair), never joining a second one.
        mm = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == invite.org_id, OrgMember.user_id == user.id
            )
        )
        if mm.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=403,
                detail="This account is managed and is tied to another organization.",
            )

    # ── join the org (idempotent) ────────────────────────────────────────────────
    mr = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == invite.org_id, OrgMember.user_id == user.id
        )
    )
    if mr.scalar_one_or_none() is None:
        from src.services.billing_limits import enforce_user_quota
        await enforce_user_quota(invite.org_id)
        role = OrgRole(invite.role) if invite.role in OrgRole._value2member_map_ else OrgRole.member
        db.add(OrgMember(
            id=str(uuid.uuid4()),
            org_id=invite.org_id,
            user_id=user.id,
            role=role,
        ))
    user.active_org_id = invite.org_id

    device_name = (req.device_name or "Nexora CLI").strip()[:100] or "Nexora CLI"

    # ── mint a user-level API key (durable credential) ───────────────────────────
    key_count = await db.execute(select(func.count()).select_from(UserApiKey).where(UserApiKey.user_id == user.id))
    if key_count.scalar_one() >= _MAX_KEYS:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_KEYS} API keys reached for this account")
    raw_key = "nxr_" + secrets.token_hex(32)
    db.add(UserApiKey(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=device_name,
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        prefix=raw_key[:12],
        created_at=datetime.now(timezone.utc),
    ))

    # ── mint a device token (shows in Settings -> Devices, revocable) ────────────
    live_devices = await db.execute(
        select(func.count()).select_from(DeviceToken).where(
            DeviceToken.user_id == user.id, DeviceToken.revoked_at.is_(None)
        )
    )
    if live_devices.scalar_one() >= _MAX_DEVICES:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_DEVICES} paired devices reached")
    platform = (req.platform or "unknown").lower()
    if platform not in ("linux", "darwin", "windows", "unknown"):
        platform = "unknown"
    raw_device = "nxd_" + secrets.token_hex(32)
    db.add(DeviceToken(
        user_id=user.id,
        org_id=invite.org_id,
        name=device_name,
        platform=platform,
        token_hash=hashlib.sha256(raw_device.encode()).hexdigest(),
        last_seen_at=datetime.now(timezone.utc),
    ))

    # ── consume the invite (single use) ──────────────────────────────────────────
    invite.accepted_at = datetime.now(timezone.utc)

    org_r = await db.execute(select(Organization).where(Organization.id == invite.org_id))
    org = org_r.scalar_one_or_none()

    from src.services.audit import record_audit
    await record_audit(
        db, action="org.invite.cli_redeem", user=user, org_id=invite.org_id,
        resource_type="org_invite", resource_id=invite.id,
        detail={"created_account": created, "platform": platform},
    )
    await db.commit()

    return CliRedeemResponse(
        access_token=create_access_token(user.id, invite.org_id, token_version=user.token_version),
        device_token=raw_device,
        api_key=raw_key,
        org_id=invite.org_id,
        org_name=org.name if org else "Unknown",
        user_email=user.email,
        user_name=user.full_name or user.email,
        created_account=created,
    )
