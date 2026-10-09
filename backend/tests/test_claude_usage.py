from datetime import datetime, timedelta, timezone

from src.providers import claude_usage as cu

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)


def test_is_limit_error():
    assert cu.is_limit_error("You've hit your session limit · resets 12:50am (Europe/Madrid)")
    assert cu.is_limit_error("Claude AI usage limit reached|1759999999")
    assert cu.is_limit_error("API Error: 429 rate_limit_error")
    assert not cu.is_limit_error("Hello, here is your answer")
    assert not cu.is_limit_error(None)


def test_cooldown_from_epoch():
    at = int((NOW + timedelta(hours=2)).timestamp())
    assert cu.cooldown_from_text(f"Claude AI usage limit reached|{at}", NOW) == 7200 + 60


def test_cooldown_from_epoch_in_past_falls_back():
    at = int((NOW - timedelta(hours=1)).timestamp())
    assert cu.cooldown_from_text(f"usage limit reached|{at}", NOW) == cu.DEFAULT_LIMIT_SECONDS


def test_cooldown_from_wall_clock_zone():
    # 20:00 UTC = 22:00 Madrid (CEST); next 12:50am Madrid is 2h50m away
    text = "You've hit your session limit · resets 12:50am (Europe/Madrid)"
    assert cu.cooldown_from_text(text, NOW) == 2 * 3600 + 50 * 60 + 60


def test_cooldown_default():
    assert cu.cooldown_from_text("429 too many requests", NOW) == cu.DEFAULT_LIMIT_SECONDS


def test_exhausted_seconds_uses_latest_exhausted_window():
    usage = {
        "session": {"percent": 100, "resets_at": (NOW + timedelta(hours=1)).isoformat()},
        "weekly": {"percent": 100, "resets_at": (NOW + timedelta(days=2)).isoformat()},
    }
    assert cu.exhausted_seconds(usage, NOW) == 2 * 86400 + 30


def test_exhausted_seconds_ignores_available_and_missing():
    assert cu.exhausted_seconds(None, NOW) is None
    assert cu.exhausted_seconds({"session": {"percent": 99, "resets_at": NOW.isoformat()}, "weekly": None}, NOW) is None
    past = {"session": {"percent": 100, "resets_at": (NOW - timedelta(hours=1)).isoformat()}, "weekly": None}
    assert cu.exhausted_seconds(past, NOW) is None


def test_exhausted_seconds_accepts_z_suffix():
    usage = {"session": {"percent": 100, "resets_at": "2026-10-09T21:00:00Z"}, "weekly": None}
    assert cu.exhausted_seconds(usage, NOW) == 3600 + 30
