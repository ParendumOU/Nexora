"""Mode (flash/think/deep) → provider-native reasoning params, capability-gated."""
from src.providers.reasoning import (
    mode_level, anthropic_thinking, openai_reasoning_effort, gemini_thinking_budget,
)


def test_mode_level():
    assert mode_level("flash") == "off"
    assert mode_level("think") == "medium"
    assert mode_level("deep") == "high"
    assert mode_level(None) == "off"
    assert mode_level("weird") == "off"


def test_anthropic_thinking_gated():
    # flash → no thinking
    assert anthropic_thinking("flash", "claude-sonnet-4") is None
    # think/deep on a reasoning-capable Claude → enabled with a budget
    t = anthropic_thinking("think", "claude-sonnet-4-20250514")
    assert t and t["type"] == "enabled" and t["budget_tokens"] >= 1024
    assert anthropic_thinking("deep", "claude-3-7-sonnet")["budget_tokens"] >= anthropic_thinking("think", "claude-sonnet-4")["budget_tokens"]
    # non-reasoning / non-claude → None (never send the param)
    assert anthropic_thinking("deep", "claude-3-5-sonnet") is None
    assert anthropic_thinking("deep", "gpt-4o") is None


def test_openai_reasoning_effort_gated():
    assert openai_reasoning_effort("flash", "openai", "o3") is None
    assert openai_reasoning_effort("think", "openai", "o3-mini") == "medium"
    assert openai_reasoning_effort("deep", "openai", "gpt-5") == "high"
    # non-reasoning model or non-openai provider → None
    assert openai_reasoning_effort("deep", "openai", "gpt-4o") is None
    assert openai_reasoning_effort("deep", "groq", "o3") is None


def test_gemini_thinking_budget_gated():
    assert gemini_thinking_budget("flash", "gemini-2.5-flash") == 0
    assert gemini_thinking_budget("deep", "gemini-2.5-pro") and gemini_thinking_budget("deep", "gemini-2.5-pro") > 0
    # no thinking knob → None (leave request unchanged)
    assert gemini_thinking_budget("deep", "gemini-1.5-pro") is None
