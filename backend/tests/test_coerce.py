"""Defensive scalar coercion for tool args — a weak model emits wrong JSON scalar types,
asyncpg rejects them on INSERT. These helpers normalize whatever the model produced so an
autonomous run doesn't crash (e.g. platform_create_agent max_tokens, issue priority)."""
from src.services.agent_tools.coerce import to_int, to_float, to_str, to_list


def test_to_int():
    assert to_int(8192) == 8192
    assert to_int("8192") == 8192          # the platform_create_agent crash
    assert to_int("8192.0") == 8192
    assert to_int(4096.0) == 4096
    assert to_int(True) == 1
    assert to_int(None, 8192) == 8192
    assert to_int("", 8192) == 8192
    assert to_int("not a number", 8192) == 8192


def test_to_float():
    assert to_float(0.7) == 0.7
    assert to_float("0.7") == 0.7          # weak model sends temperature as a string
    assert to_float(1) == 1.0
    assert to_float(None, 0.3) == 0.3
    assert to_float("nope", 0.3) == 0.3


def test_to_str():
    assert to_str("x") == "x"
    assert to_str(123) == "123"            # the issue-create "expected str, got int" crash
    assert to_str(None) is None
    assert to_str(None, "default") == "default"


def test_to_list():
    assert to_list(["a", "b"]) == ["a", "b"]
    assert to_list("bug") == ["bug"]       # single scalar where a list was expected
    assert to_list("a, b, c") == ["a", "b", "c"]
    assert to_list("") == []
    assert to_list(None) == []
    assert to_list(5) == [5]
    assert to_list(("a", "b")) == ["a", "b"]
