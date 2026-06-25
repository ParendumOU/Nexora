"""File-delivery filename sanitization (broken attachment names)."""
from src.services.agent_tools import (
    sanitize_delivery_name, split_delivery_path, looks_like_real_file, _BARE_TOOLCALLS_RE,
)


def test_real_file_detection():
    assert looks_like_real_file("pitch.md", "# p")
    assert looks_like_real_file("docs/x.html", "<html>")
    assert looks_like_real_file("page", "<!doctype html>" + "x" * 300)  # no ext but clearly html
    # junk the model fences (no ext, not file-like content) → not delivered
    assert not looks_like_real_file("syntax", "Here is the fence syntax explanation")
    assert not looks_like_real_file("deliverable", "some short note")
    assert not looks_like_real_file("fence", "")


def test_bare_toolcalls_scrub():
    s = 'Done.tool_calls [{"name":"task_update","args":{"status":"completed"}}]'
    assert _BARE_TOOLCALLS_RE.sub("", s).strip() == "Done."
    s2 = 'text ```tool_calls``` [{"name":"x","args":{}}] more'
    assert "task_update" not in _BARE_TOOLCALLS_RE.sub("", 'a tool_calls [{"name":"task_update","args":{}}]')


def test_keeps_good_names():
    assert sanitize_delivery_name("pitch.md", "# Pitch") == "pitch.md"
    assert sanitize_delivery_name("pitch_demo_v2.html", "<html>") == "pitch_demo_v2.html"


def test_strips_trailing_punct_and_quotes():
    # the observed breakage: fence. / fence" / fence."
    assert sanitize_delivery_name('fence."', "# doc").startswith("deliverable")  # "fence" is junk → generic
    assert sanitize_delivery_name('report".', "# r") .endswith(".md")
    assert sanitize_delivery_name('"notes.txt"', "x") == "notes.txt"


def test_drops_language_hint_after_path():
    assert sanitize_delivery_name("card.html html", "<html>") == "card.html"


def test_takes_basename():
    assert sanitize_delivery_name("a/b/c/plan.md", "# p") == "plan.md"
    assert sanitize_delivery_name("C:\\\\tmp\\\\x.json", "{}") == "x.json"


def test_infers_extension_when_missing():
    assert sanitize_delivery_name("readme", "# Title\n\ncontent").endswith(".md")
    assert sanitize_delivery_name("page", "<!doctype html>").endswith(".html")
    assert sanitize_delivery_name("data", "{\"a\":1}").endswith(".json")
    assert sanitize_delivery_name("script", "import os").endswith(".py")


def test_junk_names_become_generic():
    assert sanitize_delivery_name("fence", "x", index=0) == "deliverable.txt" or sanitize_delivery_name("fence", "x").startswith("deliverable")
    assert sanitize_delivery_name("", "x").startswith("deliverable")


def test_split_path_folder_and_name():
    assert split_delivery_path("docs/pitch.md", "# p") == ("docs", "pitch.md")
    assert split_delivery_path("src/web/index.html", "<html>") == ("src/web", "index.html")
    assert split_delivery_path("pitch.md", "# p") == ("", "pitch.md")


def test_split_path_rejects_traversal_and_abs():
    folder, name = split_delivery_path("../../etc/passwd", "x")
    assert ".." not in folder and name == "passwd.txt" or name.startswith("passwd")
    folder2, _ = split_delivery_path("/abs/secret/notes.md", "# n")
    assert not folder2.startswith("/")


def test_split_path_drops_language_hint():
    assert split_delivery_path("docs/card.html html", "<html>") == ("docs", "card.html")
