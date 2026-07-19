"""WebSocket authentication helper."""
import hashlib
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import WebSocket
from src.core.database import AsyncSessionLocal
from src.core.security import decode_token
from src.models.user import User

# Subprotocol scheme used to carry the auth token off the URL (GitLab #159).
# Browsers can't set WS headers but can offer subprotocols, so clients send
# `new WebSocket(url, [WS_AUTH_SUBPROTOCOL, token])`. The server reads the token
# from the offered subprotocols and echoes back ONLY the scheme on accept.
WS_AUTH_SUBPROTOCOL = "nexora-bearer"


def extract_ws_token(websocket: WebSocket) -> str | None:
    """Resolve the auth token from (in priority order): the auth subprotocol, an
    Authorization: Bearer header, then the legacy ?token= query param.

    The query param is retained for backward compatibility with un-migrated clients
    but is discouraged — it leaks into server/proxy access logs (#159). The
    subprotocol path keeps the token out of the URL entirely."""
    # 1. Subprotocol: [scheme, token, ...] — starlette parses Sec-WebSocket-Protocol.
    subprotocols = list(websocket.scope.get("subprotocols", []) or [])
    if WS_AUTH_SUBPROTOCOL in subprotocols:
        idx = subprotocols.index(WS_AUTH_SUBPROTOCOL)
        if idx + 1 < len(subprotocols):
            tok = subprotocols[idx + 1].strip()
            if tok:
                return tok
    # 2. Authorization header (native WS clients — CLI/mobile can set this).
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok:
            return tok
    # 3. Legacy query param.
    tok = websocket.query_params.get("token")
    return tok or None


def ws_accept_subprotocol(websocket: WebSocket) -> str | None:
    """If the client offered the auth subprotocol, the server MUST echo it on accept
    (RFC 6455) — return it so the caller passes it to websocket.accept(). Returns the
    scheme only, never the token."""
    if WS_AUTH_SUBPROTOCOL in (websocket.scope.get("subprotocols", []) or []):
        return WS_AUTH_SUBPROTOCOL
    return None


async def authenticate_ws(websocket: WebSocket) -> User | None:
    token = extract_ws_token(websocket)
    if not token:
        return None

    if token.startswith("nxr_"):
        from src.models.user_api_key import UserApiKey
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(UserApiKey).where(UserApiKey.key_hash == key_hash))
            api_key = result.scalar_one_or_none()
            if not api_key:
                return None
            result = await db.execute(select(User).where(User.id == api_key.user_id))
            user = result.scalar_one_or_none()
            if not user or not user.is_active:
                return None
            api_key.last_used_at = datetime.now(timezone.utc)
            await db.commit()
            # #177: carry the key's capability scope + org allowlist onto the user so
            # the socket enforces them (a read-only key must not drive a write turn,
            # and an org-restricted key must not open a foreign org's chat).
            user._api_key_scopes = api_key.scopes or None  # type: ignore[attr-defined]
            user._api_key_allowed_org_ids = api_key.allowed_org_ids or None  # type: ignore[attr-defined]
            return user

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        # Reject a 2FA-pending token on the socket too (#161).
        if payload.get("scope") == "2fa_pending":
            return None
        user_id = payload.get("sub")
    except Exception:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
