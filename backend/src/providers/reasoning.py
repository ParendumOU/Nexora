"""Map the chat Mode (flash / think / deep) to provider-native reasoning controls.

Programmatic — the way a developer drives reasoning via the API — not via prompt.
Each provider exposes reasoning differently and only on certain models, so every
helper is capability-gated (model-name sniff) and returns None when unsupported,
so we never send a param the model would 400 on. The MODE_PREFIXES prompt prefix
stays as a soft fallback for models with no native reasoning knob.

Levels: flash → reasoning OFF/minimal · think → medium · deep → high.
"""
from __future__ import annotations

_LEVEL = {"flash": "off", "think": "medium", "deep": "high"}


def mode_level(mode: str | None) -> str:
    return _LEVEL.get((mode or "flash").lower(), "off")


def _budget(level: str) -> int:
    return 12000 if level in ("high", "deep") else 4096


def anthropic_thinking(mode: str | None, model: str | None) -> dict | None:
    """`thinking` param for Anthropic extended thinking, gated to reasoning-capable
    Claude models (3.7 / 4.x). None → no thinking (flash, or unsupported model)."""
    level = mode_level(mode)
    if level == "off":
        return None
    m = (model or "").lower()
    if not any(s in m for s in ("claude-3-7", "claude-3.7", "3-7-sonnet",
                                "sonnet-4", "opus-4", "haiku-4", "claude-4")):
        return None
    return {"type": "enabled", "budget_tokens": _budget(level)}


def openai_reasoning_effort(mode: str | None, provider_type: str | None, model: str | None) -> str | None:
    """`reasoning_effort` ("medium"/"high") for OpenAI reasoning models (o-series /
    gpt-5). None → omit the param (non-reasoning model, or flash)."""
    level = mode_level(mode)
    if level == "off":
        return None
    if provider_type not in ("openai", "azure"):
        return None
    m = (model or "").lower()
    if not (m.startswith(("o1", "o3", "o4")) or "gpt-5" in m or "reasoning" in m):
        return None
    return "high" if level in ("high", "deep") else "medium"


def gemini_thinking_budget(mode: str | None, model: str | None) -> int | None:
    """`thinking_budget` for Gemini 2.5 thinking. 0 disables (flash); a budget for
    think/deep. None → leave the request unchanged (model has no thinking knob)."""
    m = (model or "").lower()
    if not ("2.5" in m or "2-5" in m or "thinking" in m):
        return None
    level = mode_level(mode)
    return 0 if level == "off" else _budget(level)
