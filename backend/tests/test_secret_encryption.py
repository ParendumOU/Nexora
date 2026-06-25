"""Encryption-at-rest for integration/MCP secrets (#186, #187)."""
from src.core.security import encrypt, decrypt, encrypt_opt, decrypt_safe


def test_encrypt_roundtrip():
    assert decrypt(encrypt("s3cr3t")) == "s3cr3t"


def test_encrypt_opt_passes_falsy():
    assert encrypt_opt(None) is None
    assert encrypt_opt("") == ""
    assert decrypt(encrypt_opt("x")) == "x"


def test_decrypt_safe_legacy_plaintext():
    # a pre-encryption plaintext value is returned unchanged (not Fernet ciphertext)
    assert decrypt_safe("plain-legacy-token") == "plain-legacy-token"
    assert decrypt_safe(None) is None


def test_decrypt_safe_roundtrip():
    assert decrypt_safe(encrypt("abc123")) == "abc123"


def test_mcp_model_plain_auth_value():
    from src.models.mcp_server import McpServer
    m = McpServer(org_id="o", name="x", url="http://x", auth_type="bearer", auth_value=encrypt("tok"))
    assert m.plain_auth_value == "tok"
    m2 = McpServer(org_id="o", name="x", url="http://x", auth_type="bearer", auth_value="legacy-plain")
    assert m2.plain_auth_value == "legacy-plain"  # tolerates legacy


def test_integration_config_encrypted_roundtrip():
    from src.models.integration import Integration
    i = Integration(org_id="o", integration_type="telegram", name="t")
    i.set_config({"bot_token": "secret123", "allowed_chat_ids": [1, 2]})
    # stored value must NOT contain the plaintext secret
    assert "secret123" not in (i.config or "")
    assert i.get_config()["bot_token"] == "secret123"
    assert i.get_config()["allowed_chat_ids"] == [1, 2]


def test_integration_get_config_legacy_plaintext():
    import json
    from src.models.integration import Integration
    i = Integration(org_id="o", integration_type="telegram", name="t")
    i.config = json.dumps({"bot_token": "old"})  # legacy plaintext JSON
    assert i.get_config()["bot_token"] == "old"
