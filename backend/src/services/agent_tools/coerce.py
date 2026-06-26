"""Defensive scalar coercion for tool arguments.

A weak LLM (e.g. gpt-4o-mini) freely emits the wrong JSON scalar type: the string
"8192" for an integer column, the int 1 for a string priority, the bare string "bug"
where a JSON list is expected. asyncpg is strict and raises a DataError on the INSERT
("'str' object cannot be interpreted as an integer", "expected str, got int", ...),
which crashes an autonomous run.

The orchestration thesis is "be smarter in code, not via model inference" — so the
platform normalizes whatever the model emits here instead of trusting it to produce
exact types. Each helper is total: it never raises, falling back to the default.
"""
from __future__ import annotations


def to_int(v, default=None):
    """Coerce to int. Accepts ints, floats, and numeric strings ("8192", "8192.0")."""
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return default


def to_float(v, default=None):
    """Coerce to float. Accepts numbers and numeric strings ("0.7")."""
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return default


def to_str(v, default=None):
    """Coerce to str. A non-string scalar (int/float/bool) is stringified; None -> default."""
    if v is None:
        return default
    if isinstance(v, str):
        return v
    return str(v)


def to_list(v, default=None):
    """Coerce to a list. A single scalar the model gave where a list was expected is
    wrapped; a comma string ("a, b") is split; None/"" -> empty list."""
    if v is None:
        return [] if default is None else default
    if isinstance(v, list):
        return v
    if isinstance(v, tuple):
        return list(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        return [p.strip() for p in s.split(",") if p.strip()] if "," in s else [s]
    if isinstance(v, (int, float, bool)):
        return [v]
    if isinstance(v, dict):
        return [v]
    return [] if default is None else default
