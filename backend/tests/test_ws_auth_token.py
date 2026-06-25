"""WebSocket auth token extraction — subprotocol / header / query (#159).

The token must be resolvable off the URL (via subprotocol or Authorization header)
so it stops leaking into server/proxy access logs; the legacy ?token= query param
stays as a backward-compatible fallback for un-migrated clients.
"""
from types import SimpleNamespace

from src.services.agent_context.auth import (
    extract_ws_token,
    ws_accept_subprotocol,
    WS_AUTH_SUBPROTOCOL,
)


def _ws(subprotocols=None, headers=None, query=None):
    h = {k.lower(): v for k, v in (headers or {}).items()}
    q = query or {}
    return SimpleNamespace(
        scope={"subprotocols": subprotocols or []},
        headers=SimpleNamespace(get=lambda k, d="": h.get(k.lower(), d)),
        query_params=SimpleNamespace(get=lambda k, d=None: q.get(k, d)),
    )


def test_token_from_subprotocol():
    assert extract_ws_token(_ws(subprotocols=[WS_AUTH_SUBPROTOCOL, "JWT123"])) == "JWT123"


def test_token_from_authorization_header():
    assert extract_ws_token(_ws(headers={"Authorization": "Bearer HDR456"})) == "HDR456"


def test_token_from_query_param_legacy():
    assert extract_ws_token(_ws(query={"token": "QRY789"})) == "QRY789"


def test_no_token_returns_none():
    assert extract_ws_token(_ws()) is None


def test_subprotocol_takes_priority_over_query():
    ws = _ws(subprotocols=[WS_AUTH_SUBPROTOCOL, "SUB"], query={"token": "QRY"})
    assert extract_ws_token(ws) == "SUB"


def test_subprotocol_without_token_value_falls_through():
    # scheme offered but no token after it → fall back to query.
    ws = _ws(subprotocols=[WS_AUTH_SUBPROTOCOL], query={"token": "QRY"})
    assert extract_ws_token(ws) == "QRY"


def test_accept_echoes_only_scheme():
    assert ws_accept_subprotocol(_ws(subprotocols=[WS_AUTH_SUBPROTOCOL, "secret"])) == WS_AUTH_SUBPROTOCOL
    # the token value is never returned as the accepted subprotocol
    assert ws_accept_subprotocol(_ws(subprotocols=[WS_AUTH_SUBPROTOCOL, "secret"])) != "secret"


def test_accept_none_when_not_offered():
    assert ws_accept_subprotocol(_ws()) is None
    assert ws_accept_subprotocol(_ws(query={"token": "x"})) is None
