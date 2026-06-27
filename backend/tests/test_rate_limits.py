"""Modular rate-limit detection engine (providers/rate_limits.py)."""
import pytest

from src.providers import rate_limits as rl


def test_opencode_go_5h_parses_reset_time():
    # "Resets in 2hr 16min" -> 2*3600 + 16*60 + 60 buffer
    cd = rl.detect_cooldown(
        "opencode-go", error_type="GoUsageLimitError",
        message="5-hour usage limit reached. Resets in 2hr 16min.",
    )
    assert cd == 2 * 3600 + 16 * 60 + 60


def test_opencode_go_5h_falls_back_to_default_when_no_time():
    cd = rl.detect_cooldown("opencode-go", error_type="GoUsageLimitError", message="limit reached")
    assert cd == 18000  # seed default_seconds (5h)


def test_free_usage_limit_days():
    cd = rl.detect_cooldown(
        "opencode-go", error_type="FreeUsageLimitError",
        message="Free tier exhausted. Resets in 1 day.",
    )
    assert cd == 86400 + 60


def test_generic_burst_message_any_provider():
    assert rl.detect_cooldown("openai", message="Rate limit. Please try again in 2m") == 120
    assert rl.detect_cooldown("groq", message="try again in 90s") == 90
    # sub-second rounds up to the 1s floor
    assert rl.detect_cooldown("openai", message="try again in 680ms") == 1


def test_no_match_returns_none():
    assert rl.detect_cooldown("openai", error_type="", message="some unrelated error") is None
    assert rl.detect_cooldown("opencode-go", message="") is None


def test_extra_rules_take_priority():
    # An org override rule is tried before seed/builtin.
    extra = [{
        "name": "custom", "match": "GoUsageLimitError",
        "default_seconds": 42, "buffer_seconds": 0,
    }]
    cd = rl.detect_cooldown(
        "opencode-go", error_type="GoUsageLimitError",
        message="Resets in 2hr 16min", extra_rules=extra,
    )
    assert cd == 42


def test_seed_rules_loaded_for_opencode_go():
    rules = rl.effective_rules("opencode-go")
    assert any(r.get("match") == "GoUsageLimitError" for r in rules)


def test_unit_parsing_hours_minutes_seconds():
    rule = {"match": "x", "reset_regex": r"(\d+)h\s*(\d+)m\s*(\d+)s", "reset_units": ["h", "m", "s"]}
    assert rl._parse_reset(rule, "1h 2m 3s") == pytest.approx(3723.0)
