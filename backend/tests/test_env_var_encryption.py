"""Agent/project env_vars encrypted at rest (#163, #172)."""
from src.core.security import encrypt_env_map, decrypt_env_map


def test_env_map_roundtrip():
    plain = {"API_KEY": "sk-secret", "NUM": 42}
    enc = encrypt_env_map(plain)
    assert enc["API_KEY"] != "sk-secret"            # value encrypted
    assert "API_KEY" in enc                          # key stays plaintext
    dec = decrypt_env_map(enc)
    assert dec["API_KEY"] == "sk-secret"
    assert dec["NUM"] == "42"                         # non-str JSON-encoded


def test_decrypt_map_legacy_plaintext():
    # a legacy plaintext map decrypts to itself (values not Fernet)
    assert decrypt_env_map({"K": "plainval"}) == {"K": "plainval"}


def test_empty_maps():
    assert encrypt_env_map({}) == {}
    assert encrypt_env_map(None) == {}
    assert decrypt_env_map(None) == {}


def test_agent_model_plain_env_vars():
    from src.models.agent import Agent
    a = Agent(org_id="o", name="x", env_vars=encrypt_env_map({"TOKEN": "abc"}))
    # stored map must not contain the plaintext secret
    assert "abc" not in str(a.env_vars)
    assert a.plain_env_vars == {"TOKEN": "abc"}
