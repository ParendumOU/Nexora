"""Security hardening (P5): workspace path confinement, local-exec user binding,
agent env_vars masking. HTTP/SSRF/WS paths are covered by test_ssrf.py +
test_secret_guard.py + integration; these are the unit-testable pure pieces.
"""
import uuid

import pytest


# ── workspace path confinement (file_* tools) ───────────────────────────────

@pytest.mark.asyncio
async def test_resolve_path_guarded_blocks_sensitive_paths_legacy_mode(monkeypatch):
    import src.services.workspace as ws
    # Workspace off → legacy mode, but sensitive host paths still denied.
    monkeypatch.setattr(ws, "resolve_workspace_dir", _async_none)

    for bad in ("/app/.env", "/proc/self/environ", "/root/.ssh/id_rsa", "/etc/shadow"):
        path, err = await ws.resolve_path_guarded("chat", bad)
        assert path is None and err, f"expected block for {bad}"

    # A normal relative path passes in legacy mode.
    path, err = await ws.resolve_path_guarded("chat", "notes.txt")
    assert err is None and path == "notes.txt"


@pytest.mark.asyncio
async def test_resolve_path_guarded_confines_to_workspace(monkeypatch, tmp_path):
    import src.services.workspace as ws
    wsdir = str(tmp_path / "proj_x")
    import os
    os.makedirs(wsdir, exist_ok=True)

    async def _ws(_chat):
        return wsdir
    monkeypatch.setattr(ws, "resolve_workspace_dir", _ws)

    # In-workspace relative path → resolved under the workspace.
    path, err = await ws.resolve_path_guarded("chat", "src/main.py")
    assert err is None and path.startswith(os.path.realpath(wsdir) + os.sep)

    # Traversal escape → blocked.
    path, err = await ws.resolve_path_guarded("chat", "../../etc/passwd")
    assert path is None and "escapes" in err

    # Absolute path outside the workspace → blocked.
    path, err = await ws.resolve_path_guarded("chat", "/app/.env")
    assert path is None and err


async def _async_none(_chat):
    return None


# ── local-exec user binding ─────────────────────────────────────────────────

def test_local_tools_active_binds_to_owner():
    from src.services.agent_tools import local_exec as le

    chat_id = str(uuid.uuid4())
    owner = "user-A"
    bridge = le.LocalExecBridge(chat_id, send=None, owner_user_id=owner)
    le._bridges[chat_id] = bridge
    try:
        # No turn user set → not the owner → denied.
        le.current_turn_user.set(None)
        assert le.local_tools_active(chat_id) is False

        # A different user's turn → denied (the shared-chat exploit).
        le.current_turn_user.set("user-B")
        assert le.local_tools_active(chat_id) is False

        # The owner's own turn → granted.
        le.current_turn_user.set(owner)
        assert le.local_tools_active(chat_id) is True
    finally:
        le._bridges.pop(chat_id, None)
        le.current_turn_user.set(None)


def test_local_tools_active_legacy_bridge_without_owner():
    from src.services.agent_tools import local_exec as le
    chat_id = str(uuid.uuid4())
    le._bridges[chat_id] = le.LocalExecBridge(chat_id, send=None, owner_user_id=None)
    try:
        le.current_turn_user.set("anyone")
        assert le.local_tools_active(chat_id) is True  # single-user chats unaffected
    finally:
        le._bridges.pop(chat_id, None)
        le.current_turn_user.set(None)


def test_local_tools_active_no_bridge():
    from src.services.agent_tools import local_exec as le
    assert le.local_tools_active(str(uuid.uuid4())) is False


# ── agent env_vars masking ──────────────────────────────────────────────────

def test_agent_response_masks_env_vars_and_reveal_decrypts():
    from src.core.security import encrypt_env_map
    from src.api.routers.agents import AgentResponse, _ENV_MASK

    encrypted = encrypt_env_map({"API_KEY": "super-secret-value", "REGION": "eu"})
    resp = AgentResponse(
        id="a", name="A", agent_type="custom", env_vars=dict(encrypted),
    )
    # Masked by default — no plaintext, no ciphertext leaked.
    assert set(resp.env_vars.keys()) == {"API_KEY", "REGION"}
    assert all(v == _ENV_MASK for v in resp.env_vars.values())
    assert "super-secret-value" not in resp.env_vars.values()

    # Reveal (member+) decrypts back to real values.
    resp.reveal_env_vars(encrypted)
    assert resp.env_vars == {"API_KEY": "super-secret-value", "REGION": "eu"}
