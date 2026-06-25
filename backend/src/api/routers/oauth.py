"""OAuth 2.0 social login — Google and GitHub.

Endpoints:
  GET /auth/oauth/{provider}           → redirect to provider
  GET /auth/oauth/{provider}/callback  → exchange code, find-or-create user, issue JWT
"""
import secrets
import urllib.parse
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import get_db
from src.core.security import create_access_token, create_refresh_token
from src.models.org import OrgMember, OrgRole, Organization
from src.models.user import User

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


@router.get("/providers")
async def oauth_providers():
    """Return which OAuth social-login providers are configured."""
    settings = get_settings()
    return {
        "google": bool(settings.google_client_id and settings.google_client_secret),
        "github": bool(settings.github_client_id and settings.github_client_secret),
    }


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:50]


@router.get("/{provider}")
async def oauth_redirect(provider: str):
    """Redirect the browser to the OAuth provider's authorization URL."""
    settings = get_settings()

    if provider == "google":
        if not settings.google_client_id:
            raise HTTPException(status_code=404, detail="Google OAuth not configured")
        callback_url = f"{settings.app_url}/api/auth/oauth/google/callback"
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": "openid email profile",
            "state": secrets.token_urlsafe(16),
        }
        return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}")

    if provider == "github":
        if not settings.github_client_id:
            raise HTTPException(status_code=404, detail="GitHub OAuth not configured")
        callback_url = f"{settings.app_url}/api/auth/oauth/github/callback"
        params = {
            "client_id": settings.github_client_id,
            "redirect_uri": callback_url,
            "scope": "user:email",
            "state": secrets.token_urlsafe(16),
        }
        return RedirectResponse(f"{GITHUB_AUTH_URL}?{urllib.parse.urlencode(params)}")

    raise HTTPException(status_code=404, detail="Unknown provider")


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth provider callback: exchange code → userinfo → JWT."""
    settings = get_settings()
    frontend_url = settings.app_url

    if error:
        return RedirectResponse(f"{frontend_url}/login?error=oauth_denied")

    if not code:
        return RedirectResponse(f"{frontend_url}/login?error=no_code")

    # ── Fetch userinfo from provider ──────────────────────────────────────────
    email: str | None = None
    oauth_id: str | None = None
    name: str = ""

    try:
        if provider == "google":
            if not settings.google_client_id:
                raise HTTPException(status_code=404, detail="Google OAuth not configured")
            callback_url = f"{settings.app_url}/api/auth/oauth/google/callback"
            async with httpx.AsyncClient(timeout=15) as client:
                token_resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "redirect_uri": callback_url,
                        "grant_type": "authorization_code",
                    },
                )
                tokens = token_resp.json()
                access_token = tokens.get("access_token")
                if not access_token:
                    return RedirectResponse(f"{frontend_url}/login?error=token_exchange_failed")
                ui_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                userinfo = ui_resp.json()
            email = userinfo.get("email")
            oauth_id = str(userinfo.get("id") or userinfo.get("sub") or "")
            name = userinfo.get("name", "")

        elif provider == "github":
            if not settings.github_client_id:
                raise HTTPException(status_code=404, detail="GitHub OAuth not configured")
            callback_url = f"{settings.app_url}/api/auth/oauth/github/callback"
            async with httpx.AsyncClient(timeout=15) as client:
                token_resp = await client.post(
                    GITHUB_TOKEN_URL,
                    data={
                        "client_id": settings.github_client_id,
                        "client_secret": settings.github_client_secret,
                        "code": code,
                        "redirect_uri": callback_url,
                    },
                    headers={"Accept": "application/json"},
                )
                tokens = token_resp.json()
                gh_token = tokens.get("access_token")
                if not gh_token:
                    return RedirectResponse(f"{frontend_url}/login?error=token_exchange_failed")
                user_resp = await client.get(
                    GITHUB_USER_URL,
                    headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/json"},
                )
                gh_user = user_resp.json()
                emails_resp = await client.get(
                    GITHUB_EMAILS_URL,
                    headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/json"},
                )
                emails = emails_resp.json() if isinstance(emails_resp.json(), list) else []
                primary_email = next(
                    (e["email"] for e in emails if isinstance(e, dict) and e.get("primary")),
                    None,
                )
                email = primary_email or gh_user.get("email")
                oauth_id = str(gh_user.get("id", ""))
                name = gh_user.get("name") or gh_user.get("login", "")

        else:
            raise HTTPException(status_code=404, detail="Unknown provider")

    except HTTPException:
        raise
    except Exception:
        return RedirectResponse(f"{frontend_url}/login?error=provider_error")

    if not email:
        return RedirectResponse(f"{frontend_url}/login?error=no_email")

    # ── Find or create user ───────────────────────────────────────────────────
    user = await db.scalar(select(User).where(User.email == email))

    if not user:
        # Auto-register the user and create their personal org
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            email=email,
            full_name=name or email.split("@")[0],
            hashed_password=f"oauth:{secrets.token_hex(32)}",
            is_active=True,
            is_verified=True,
            oauth_provider=provider,
            oauth_id=oauth_id,
        )
        db.add(user)
        await db.flush()

        # Create personal org
        org_name = f"{user.full_name}'s Workspace"
        base_slug = _slugify(org_name)
        slug = base_slug
        i = 1
        while True:
            existing = await db.scalar(select(Organization).where(Organization.slug == slug))
            if not existing:
                break
            slug = f"{base_slug}-{i}"
            i += 1

        org = Organization(
            id=str(uuid.uuid4()),
            name=org_name,
            slug=slug,
            owner_id=user.id,
            is_personal=True,
        )
        db.add(org)
        await db.flush()

        member = OrgMember(
            id=str(uuid.uuid4()),
            org_id=org.id,
            user_id=user.id,
            role=OrgRole.owner,
        )
        db.add(member)
        user.active_org_id = org.id
        await db.commit()
        await db.refresh(user)

    else:
        # Existing user — backfill OAuth fields if not set
        if not user.oauth_provider:
            user.oauth_provider = provider
            user.oauth_id = oauth_id
            await db.commit()

    # ── Issue JWT ─────────────────────────────────────────────────────────────
    org_id = user.active_org_id
    if not org_id:
        result = await db.execute(
            select(OrgMember).where(OrgMember.user_id == user.id).limit(1)
        )
        member = result.scalar_one_or_none()
        if member:
            org_id = member.org_id

    access_token_jwt = create_access_token(user.id, org_id, token_version=user.token_version)
    refresh_token_jwt = create_refresh_token(user.id, user.token_version)

    return RedirectResponse(
        f"{frontend_url}/auth/oauth-callback"
        f"?token={access_token_jwt}"
        f"&refresh={refresh_token_jwt}"
    )
