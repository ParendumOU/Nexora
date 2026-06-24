"""Chat-title sanitizer rejects leaked model reasoning (weak-model robustness)."""
from src.services.chat_title import _clean_title, _looks_like_reasoning


def test_rejects_the_real_leaked_reasoning_title():
    bad = 'But wait: I should not include "response" as that\'s from instruction. The title'
    assert _looks_like_reasoning(_clean_title(bad)) is True


def test_clean_strips_think_block_and_takes_final_line():
    raw = "<think>The user wants a title. Let me pick one.</think>\nBioluminescent Bio Cards"
    assert _clean_title(raw) == "Bioluminescent Bio Cards"


def test_clean_takes_last_line_after_reasoning():
    raw = "Okay, the conversation is about cards.\nProduct Card Design"
    assert _clean_title(raw) == "Product Card Design"


def test_clean_strips_label_and_quotes():
    assert _clean_title('Title: "Bio Cards"') == "Bio Cards"
    assert _clean_title("respuesta: Bio Cards.") == "Bio Cards"


def test_good_title_accepted():
    for t in ["Bioluminescent Bio Cards", "Braindump setup pending", "Deploy runner service"]:
        assert _looks_like_reasoning(t) is False


def test_reasoning_markers_and_length_flagged():
    assert _looks_like_reasoning("Let me think about this") is True
    assert _looks_like_reasoning("What should the title be?") is True   # question mark
    assert _looks_like_reasoning("one two three four five six seven eight nine ten") is True  # >9 words
