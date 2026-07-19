"""Agent tool execution — task/issue/skill/platform tools invoked from tool_calls fences."""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import WebSocket
from src.core.database import AsyncSessionLocal
from src.models.skill import Skill
from src.models.tool import Tool

# Re-export everything external callers depend on
from src.services.agent_tools.task_helpers import (
    _ws_status,
    _task_to_dict,
    _resolve_agent_id,
    _bubble_complete_parent,
    _fail_task,
)
from src.services.agent_tools.tool_executor import (
    _build_executor_registry,
    _get_executor,
    _parse_tool_calls,
    _run_single_tool,
    deliver_inline_file,
    auto_deliver_written_file,
    is_executable_tool,
)
from src.services.agent_tools.skill_runner import (
    _build_skill_registry,
    _get_skill_registry,
    _resolve_skill_tool,
    _to_cli_args,
    _run_skill_tool,
)
from src.services.agent_tools.tool_permissions import (
    _always_allowed,
    _optional_builtins,
    _get_agent_enabled_tools,
    is_tool_allowed,
)
from src.services.agent_tools.tool_schemas import validate_tool_args

logger = logging.getLogger(__name__)

# Native/internal tool names CLI providers may leak into their text response as
# bogus tool_calls (their own agent loop, not Nexora's). Ignored by the parser
# so they don't generate "Unknown tool" failures that loop the orchestrator.
# (MCP tools also leak with an `mcp__` prefix — handled separately.)
# NOTE: only names that are NOT also valid Nexora tool/skill keys. Gemini's
# read_file/write_file collide with real Nexora skills, so they are deliberately
# excluded here (a genuine call must still run).
_CLI_INTERNAL_TOOLS = {
    "update_topic", "save_memory", "google_web_search", "web_fetch",
    "run_shell_command", "read_many_files", "list_directory",
    "search_file_content",
}

_TOOL_FENCE_RE = re.compile(
    r'```(?:tool_calls|json|tools)?\s*\n(?:tool_calls|json|tools)\n([\s\S]*?)\n?```'
    r'|```(?:tool_calls|json|tools)\s*\n([\s\S]*?)\n?```'
    # Empty fence where LLM writes "tool_calls [...]" inline (e.g. ```\ntool_calls [{...}]\n```)
    r'|```[ \t]*\n(tool_calls\s*[\[{][\s\S]*?)\n?```',
    re.IGNORECASE,
)

# Greedy fallback: used when lazy match produces malformed JSON (e.g. embedded ``` inside a string value)
_TOOL_FENCE_GREEDY_RE = re.compile(
    r'```(?:tool_calls|json|tools)?\s*\n(?:tool_calls|json|tools)\n([\s\S]*)\n?```'
    r'|```(?:tool_calls|json|tools)\s*\n([\s\S]*)\n?```'
    r'|```[ \t]*\n(tool_calls\s*[\[{][\s\S]*)\n?```',
    re.IGNORECASE,
)

# Truncated-fence fallback: LLM hit max_tokens before closing ```. Match from fence open to end of string.
_TOOL_FENCE_TRUNCATED_RE = re.compile(
    r'```(?:tool_calls|json|tools)?\s*\n(?:tool_calls|json|tools)\n([\s\S]+)\Z'
    r'|```(?:tool_calls|json|tools)\s*\n([\s\S]+)\Z'
    r'|```[ \t]*\n(tool_calls\s*[\[{][\s\S]+)\Z',
    re.IGNORECASE,
)

# XML-style <tool_calls> format — LLM occasionally uses this instead of backtick fences.
# Normalise to backtick format before the main regex runs.
_XML_TOOL_CALLS_RE = re.compile(r'<tool_calls>([\s\S]*?)</tool_calls>', re.IGNORECASE)

# <|tool_call|> or <|tool_calls|> ... <|end|> — special-token format used by some instruct models
# (Qwen2.5, Mistral-Nemo, OpenCode variants). Normalise to backtick fence before main parser.
# Also catches <lend> which some renderers produce when stripping pipe chars from <|end|>.
_TOKEN_TOOL_CALLS_RE = re.compile(
    r'<\|tool_calls?\|>\s*([\s\S]*?)\s*(?:<\|end\|>|<lend>)',
    re.IGNORECASE,
)

_HTML_COMMENT_RE = re.compile(r'<!--[\s\S]*?-->', re.DOTALL)

# Inline file-output fence: ```file:relative/or/abs/path.ext\n<raw content>\n```
# Lets an agent deliver a file (HTML, code, CSV, …) as a downloadable attachment WITHOUT
# embedding the content inside a JSON tool-call arg — weak models routinely produce invalid
# JSON when a 10KB HTML/code blob has to be escaped into a string, silently dropping the
# whole deliverable. The raw fence is just a labelled code block, so it always survives.
# The optional 4th capture lets the language follow the path (```file:card.html html).
_FILE_OUTPUT_FENCE_RE = re.compile(
    r'```file:[ \t]*([^\n`]+?)[ \t]*\n([\s\S]*?)\n?```',
    re.IGNORECASE,
)

_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")


def _sniff_ext(content: str) -> str:
    """Best-effort file extension from content when the fence path lacks one."""
    head = (content or "").lstrip()[:400].lower()
    if head.startswith(("<!doctype", "<html")) or "<body" in head:
        return ".html"
    if head.startswith(("{", "[")):
        return ".json"
    if head.startswith(("def ", "import ", "from ", "class ", "#!/usr/bin/env python")):
        return ".py"
    if head.startswith(("<?xml", "<svg")):
        return ".xml"
    if head.startswith("```") or head.startswith("# ") or "## " in head:
        return ".md"
    return ".txt"


def sanitize_delivery_name(raw: str, content: str = "", *, index: int = 0) -> str:
    """Turn a model-supplied file-fence path into a safe display filename.

    Weak models emit garbage paths (``fence.``, ``fence"``, ``pitch.md md``). Strip
    quotes/whitespace/control chars, drop a trailing language hint, keep the
    basename, ensure a sane extension (inferred from content), and fall back to a
    generic name when nothing usable remains.
    """
    s = (raw or "").strip().strip("`'\"“”‘’ \t").strip()
    s = s.split()[0] if s else ""               # first token (drop "path lang" hint)
    s = s.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]  # basename
    s = re.sub(r'[<>:"|?*\x00-\x1f]', "", s)      # illegal filename chars
    s = s.strip(" .\"'`")                         # trailing dots/quotes ("fence." → "fence")
    if not s or s.lower() in ("fence", "file", "path", "filename", "code", "output"):
        s = f"deliverable_{index + 1}" if index or not s else "deliverable"
    if not _EXT_RE.search(s):
        s += _sniff_ext(content)
    return s[:120]


def looks_like_real_file(raw_path: str, content: str = "") -> bool:
    """Whether a ```file: fence is a genuine deliverable vs the model fencing junk
    (a bare word like `syntax`/`fence`, reasoning, an example). Avoids creating junk
    attachments (deliverable.txt, syntax.txt). True when the path has a real
    extension, or the content clearly IS a file (html/code/data of some size)."""
    tok = (raw_path or "").strip().strip("`'\"“”‘’ \t")
    tok = tok.split()[0] if tok else ""
    base = tok.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if _EXT_RE.search(base):
        return True
    head = (content or "").lstrip()[:200].lower()
    if len(content or "") > 200 and head.startswith((
        "<!doctype", "<html", "<?xml", "<svg", "{", "[", "def ", "import ", "class ", "#!/",
    )):
        return True
    return False


def split_delivery_path(raw: str, content: str = "", *, index: int = 0) -> tuple[str, str]:
    """Split a model-supplied file-fence path into a (folder, filename) pair for the
    thread file explorer. Folder segments are sanitized (no .., ~, abs, illegal); the
    filename reuses sanitize_delivery_name. Folder is "" for a root-level file."""
    s = (raw or "").strip().strip("`'\"“”‘’ \t")
    s = s.split()[0] if s else ""          # drop a trailing language hint
    s = s.replace("\\", "/")
    parts = [p for p in s.split("/") if p not in ("", ".", "..", "~")]
    base = parts[-1] if parts else ""
    name = sanitize_delivery_name(base, content, index=index)
    segs: list[str] = []
    for seg in parts[:-1]:
        seg = re.sub(r'[<>:"|?*\x00-\x1f]', "", seg).strip(" .").strip()
        if seg:
            segs.append(seg[:60])
    folder = "/".join(segs[:6])            # cap depth
    return folder, name


# Whole ```tool_calls|json|tools``` fence span — used only to protect a tool-call
# JSON region from the inline file-output extraction above. A task_create
# description can legitimately contain a ```file:...``` example; extracting that
# inner fence corrupts the surrounding JSON, so the call fails to parse, the raw
# JSON leaks into the chat, and the agent pointlessly retries the turn.
_ANY_TOOL_FENCE_SPAN_RE = re.compile(
    r'```(?:tool_calls|json|tools)\b[\s\S]*?```',
    re.IGNORECASE,
)

# Dangling, unfenced tool-call args fragment that escaped parsing (malformed JSON).
# Anchored on arg keys that NEVER occur in normal prose, so scrubbing it is safe.
# Removes from the start of the line carrying the key through the trailing braces.
_TOOL_RESIDUE_RE = re.compile(
    r'[^\n]*?"(?:assigned_agent_id|agent_overrides|system_prompt_append|tool_name)"\s*:[\s\S]*?\}{1,3}\s*\]?',
    re.IGNORECASE,
)

# Orphan trailing JSON-closer run left when a mangled/partial tool-call fence is
# stripped but its tail survives (weak models): e.g. '...procede directamente."}}}]'.
# A run of 2+ closing braces/brackets at the very end (optionally after a quote/comma)
# is machine residue — legitimate prose effectively never ends this way.
_ORPHAN_JSON_TAIL_RE = re.compile(r'\s*["\',]?\s*[}\]]{2,}\s*\Z')

# Bare (unfenced) `tool_calls [ {…} ]` left in content when a weak model mangles the
# fence (e.g. the path runs straight into the keyword). The keyword immediately
# followed by a JSON-object array is machine residue — never legitimate prose.
_BARE_TOOLCALLS_RE = re.compile(r'`{0,3}\s*tool_calls\s*`{0,3}\s*\[\s*\{[\s\S]*?\}\s*\]', re.IGNORECASE)

# nexora_spawn directive — the plain-text sub-agent spawn block (primary path for
# Gemini, but any provider can emit it by copying the format from history). The
# Gemini stream strips it before save; this handles every other provider so the
# raw block never leaks into the chat. Parsed + spawned in _execute_agent_tools.
_NEXORA_SPAWN_RE = re.compile(r"```nexora_spawn\s*\n([\s\S]*?)\n?```", re.IGNORECASE)


def _extract_nexora_spawn(text: str) -> tuple[str, list[dict]]:
    directives: list[dict] = []

    def _collect(m: "re.Match") -> str:
        body = (m.group(1) or "").strip()
        try:
            obj = json.loads(body)
        except Exception:
            return ""
        for d in (obj if isinstance(obj, list) else [obj]):
            if isinstance(d, dict) and (d.get("title") or d.get("task")):
                directives.append(d)
        return ""

    return _NEXORA_SPAWN_RE.sub(_collect, text).strip(), directives

# Bare `<final/>` turn-end marker. Stripped from user-visible content but the
# watchdog detector reads the raw response_text BEFORE this strip, so the
# signal still counts.
_FINAL_TAG_STRIP_RE = re.compile(
    r"<\s*final\s*/?\s*>|<\s*final\s*>\s*<\s*/\s*final\s*>",
    re.IGNORECASE,
)

# Internal-protocol prefixes the LLM occasionally echoes back. Strip from saved
# assistant content so the user never sees these in chat history.
_LEAK_PREFIX_RE = re.compile(
    r'^\s*(?:'
    r'\[Tool results[^\]]*\]'
    r'|\[Resumed[^\]]*\]'
    r'|<system_observation[^>]*>[\s\S]*?</system_observation>'
    r')\s*',
    re.IGNORECASE,
)


def _strip_protocol_leaks(text: str) -> str:
    """Remove internal-protocol prefixes that leaked into model output."""
    prev = None
    out = text
    while prev != out:
        prev = out
        out = _LEAK_PREFIX_RE.sub('', out)
    return out


async def _execute_agent_tools(
    response_text: str,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
    websocket: WebSocket | None = None,
    task_id: str | None = None,
    parent_chat_id: str | None = None,
    message_id: str | None = None,
) -> tuple[str, list[dict], list[dict], bool, str | None]:
    """Find tool_calls fences in the response, execute them, return
    (cleaned text, results, counted_calls, had_fence, parse_error).

    had_fence=False AND parse_error is None → agent sent plain text with no
    tool_calls fence at all. Caller nudges agent to use tools.

    had_fence=False AND parse_error is non-None → agent attempted a fence but
    the JSON was unrecoverable. Caller should send a targeted retry that quotes
    the parse error rather than the generic "use tools" nudge.
    """
    from src.models.task import TaskStep
    from src.core.pubsub import broadcast as _broadcast

    _status_pub = chat_id if not websocket else None

    response_text = _HTML_COMMENT_RE.sub('', response_text).strip()
    response_text = _strip_protocol_leaks(response_text)
    # Normalise XML-style <tool_calls> to backtick fence so the main parser handles it.
    response_text = _XML_TOOL_CALLS_RE.sub(
        lambda m: f"```tool_calls\n{m.group(1).strip()}\n```", response_text
    )
    # Normalise <|tool_call|>/<|tool_calls|>...<|end|> token format to backtick fence.
    response_text = _TOKEN_TOOL_CALLS_RE.sub(
        lambda m: f"```tool_calls\n{m.group(1).strip()}\n```", response_text
    )
    # NOTE: `<final/>` is intentionally NOT stripped here — the watchdog reads
    # it from the saved Message.content row. The frontend hides it for users.

    # Handle nexora_spawn directives from ANY provider (the Gemini stream already
    # strips its own; this catches non-Gemini providers that copy the format from
    # history, so the raw block never leaks into the chat). Dedup in
    # spawn_subagent_task prevents a duplicate of an already-spawned sub-agent.
    response_text, _spawn_dirs = _extract_nexora_spawn(response_text)
    if _spawn_dirs:
        from src.services.sub_agent.spawn import spawn_subagent_task, already_spawned_this_turn
        # Block a resume/fallback turn from re-spawning the same work (e.g. when
        # the orchestrator falls from Gemini to opencode-zen, which paraphrases
        # the directive — defeating exact-match dedup). Parallel spawns in one
        # batch are unaffected (they're created after this check, in this loop).
        if await already_spawned_this_turn(chat_id):
            logger.info(
                f"[tools] ignoring {len(_spawn_dirs)} nexora_spawn directive(s) — "
                f"a sub-agent was already spawned this turn for chat {chat_id}"
            )
        else:
            for _d in _spawn_dirs:
                try:
                    await spawn_subagent_task(_d, chat_id, agent_id, agent_name)
                except Exception as _exc:
                    logger.warning(f"[tools] nexora_spawn directive failed: {_exc}")

    # Inline file-output fences (```file:PATH) → deliver each as a downloadable
    # attachment. Done BEFORE tool_calls parsing so a deliverable survives even when
    # the model also emits a malformed JSON tool call in the same turn.
    # Protect tool_calls JSON regions: never extract/replace a ```file:``` fence that
    # sits INSIDE a ```tool_calls``` block (a task_create description may contain one as
    # an example). Doing so would corrupt the JSON → parse failure → raw-JSON leak + loop.
    _tool_fence_spans = [(m.start(), m.end()) for m in _ANY_TOOL_FENCE_SPAN_RE.finditer(response_text)]
    def _inside_tool_fence(pos: int) -> bool:
        return any(s <= pos < e for s, e in _tool_fence_spans)

    _file_deliveries: list[dict] = []
    _file_fence_matches = [
        m for m in _FILE_OUTPUT_FENCE_RE.finditer(response_text)
        if not _inside_tool_fence(m.start())
    ]
    for _fi, _fm in enumerate(_file_fence_matches):
        _fpath = (_fm.group(1) or "").strip()
        _fcontent = _fm.group(2) or ""
        # Skip junk fences (model fencing a bare word / example / reasoning) so we
        # don't create attachments like syntax.txt / deliverable.txt. Still stripped
        # from the visible text below (it's in _file_fence_matches).
        if not looks_like_real_file(_fpath, _fcontent):
            logger.info(f"[tools] skipping non-file ```file: fence (path={_fpath[:40]!r})")
            continue
        # Split the model-supplied path into a safe (folder, filename) so deliverables
        # land in an organized folder tree (sanitizes junk + infers a missing ext).
        _folder, _name = split_delivery_path(_fpath, _fcontent, index=_fi)
        try:
            _dres = await deliver_inline_file(chat_id, parent_chat_id, _name, _fcontent, folder=_folder)
        except Exception as _exc:
            _dres = {"error": str(_exc)}
        if "error" in _dres:
            logger.warning(f"[tools] inline file '{_name}' delivery failed: {_dres['error']}")
            _file_deliveries.append({"tool": "file_deliver", "error": _dres["error"]})
        else:
            logger.info(f"[tools] delivered inline file '{_name}' ({_dres['size_bytes']} bytes)")
            _file_deliveries.append({"tool": "file_deliver", "data": {
                "delivered": True, "name": _dres["name"],
                "download_url": _dres["download_url"], "size_bytes": _dres["size_bytes"],
                "message": f"Delivered '{_dres['name']}' to the user (Files panel) — do NOT "
                           "re-create or re-search for it.",
            }})
    if _file_fence_matches:
        # Replace ONLY the delivered (outside-tool) fences with a short marker so the raw
        # blob doesn't flood the chat. Splice in reverse to keep offsets valid; any
        # ```file:``` living inside a tool_calls JSON is left intact for the parser.
        for _fm in sorted(_file_fence_matches, key=lambda m: m.start(), reverse=True):
            _marker = f"📎 {((_fm.group(1) or 'file').strip().split() or ['file'])[0].rsplit('/', 1)[-1]}"
            response_text = response_text[:_fm.start()] + _marker + response_text[_fm.end():]
        response_text = response_text.strip()

    match = _TOOL_FENCE_RE.search(response_text)

    tool_calls = None
    raw_json = ""

    if not match:
        # Truncated-fence fallback: LLM hit max_tokens before writing closing ```.
        # Match from fence open to end of string and attempt JSON extraction.
        trunc_match = _TOOL_FENCE_TRUNCATED_RE.search(response_text)
        if trunc_match:
            trunc_json = (trunc_match.group(1) or trunc_match.group(2) or trunc_match.group(3) or "").strip()
            trunc_calls = _parse_tool_calls(trunc_json)
            if trunc_calls is not None:
                logger.info(
                    f"[tools] truncated fence recovered {len(trunc_calls)} call(s) "
                    "(no closing backticks — likely max_tokens cut-off)"
                )
                match = trunc_match
                raw_json = trunc_json
                tool_calls = trunc_calls

        if tool_calls is None:
            logger.debug(f"[tools] no tool_calls fence found in response (len={len(response_text)})")
            await _ws_status(websocket, "idle", pub_chat_id=_status_pub)
            # An inline file fence still counts as work done (had_fence=True) and its
            # delivery result drives the resume so the orchestrator confirms to the user.
            return response_text, _file_deliveries, [], bool(_file_deliveries), None

    if tool_calls is None:
        raw_json = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        logger.info(f"[tools] tool_calls fence found: {raw_json[:300]}")
        tool_calls = _parse_tool_calls(raw_json)

    if tool_calls is None:
        # Lazy match may have been cut short by an embedded ``` inside a JSON string value
        # (e.g. task_create description with a code example). Try greedy match as fallback.
        greedy_match = _TOOL_FENCE_GREEDY_RE.search(response_text)
        if greedy_match:
            greedy_json = (greedy_match.group(1) or greedy_match.group(2) or greedy_match.group(3) or "").strip()
            if greedy_json != raw_json:
                tool_calls = _parse_tool_calls(greedy_json)
                if tool_calls is not None:
                    logger.info(f"[tools] greedy fence match recovered {len(tool_calls)} call(s)")
                    match = greedy_match
                    raw_json = greedy_json

    if tool_calls is None:
        logger.warning(f"[tools] tool_calls JSON parse failed — raw: {raw_json[:400]}")
        await _ws_status(websocket, "idle", pub_chat_id=_status_pub)
        clean = response_text[:match.start()].rstrip() + response_text[match.end():]
        # The fence boundaries can be ambiguous when the bad JSON contains stray ```
        # or real newlines, so removing only `match` can leave a raw-JSON tail visible.
        # Scrub any residual fenced tool block + dangling tool-call args fragment — these
        # keys never appear in legitimate prose, so this only removes leaked machine text.
        clean = _ANY_TOOL_FENCE_SPAN_RE.sub("", clean)
        clean = _BARE_TOOLCALLS_RE.sub("", clean)
        clean = _TOOL_RESIDUE_RE.sub("", clean)
        clean = _ORPHAN_JSON_TAIL_RE.sub("", clean)
        # Caller receives parse_error so it can emit a targeted retry quoting the
        # malformed JSON (much more useful than the generic "use tools" nudge).
        # But if an inline file fence already delivered the real work this turn,
        # suppress the retry — the deliverable landed; the broken JSON was redundant.
        if _file_deliveries:
            return clean.strip(), _file_deliveries, [], True, None
        parse_err = f"Could not parse tool_calls JSON. Raw payload (first 400 chars): {raw_json[:400]}"
        return clean.strip(), [], [], False, parse_err

    clean_text = (response_text[:match.start()].rstrip() + response_text[match.end():]).strip()
    clean_text = _BARE_TOOLCALLS_RE.sub("", clean_text)
    clean_text = _ORPHAN_JSON_TAIL_RE.sub("", clean_text).rstrip()

    # Structured turn-completion signal (#213 / H1): a model seals its turn by
    # emitting the `end_turn` control tool in the fence — the JSON-native,
    # provider-agnostic equivalent of the <final/> sentinel (composes with native
    # function calling #214). It is NOT executable work, so strip it. When it was
    # the SOLE call the turn carries no resumable work → return had_fence=False so
    # the engine seals it as terminal (no resume, no watchdog re-poke). Mixed with
    # real tools, their results must still resume, so end_turn is just dropped.
    from src.services.turn_completion import strip_end_turn
    tool_calls, _had_end_turn = strip_end_turn(tool_calls)
    if _had_end_turn and not tool_calls:
        await _ws_status(websocket, "idle", pub_chat_id=_status_pub)
        return clean_text, _file_deliveries, [], bool(_file_deliveries), None

    # Resolve which optional built-in tools this agent may call
    agent_enabled = await _get_agent_enabled_tools(agent_id, chat_id)

    # Group ID for PM-level actions (no task_id = agent running directly in main chat)
    _pm_group_id = str(uuid.uuid4()) if not task_id and message_id else None

    # Batch-resolve all tool/skill display labels in a single DB round-trip
    _all_names = [c.get("name", "") for c in tool_calls if c.get("name")]
    _label_map: dict[str, str] = {}
    if _all_names:
        async with AsyncSessionLocal() as db:
            tr = await db.execute(select(Tool.key, Tool.name).where(Tool.key.in_(_all_names)))
            for tkey, tname in tr.all():
                _label_map[tkey] = f"{tname}…"
            _missing = [n for n in _all_names if n not in _label_map]
            if _missing:
                sr = await db.execute(select(Skill.key, Skill.name).where(Skill.key.in_(_missing)))
                for skey, sname in sr.all():
                    _label_map[skey] = f"{sname}…"
                _still_missing = [n for n in _missing if n not in _label_map]
                if _still_missing:
                    _prefixes = {n.split("_", 1)[0] for n in _still_missing if "_" in n}
                    if _prefixes:
                        psr = await db.execute(select(Skill.key, Skill.name).where(Skill.key.in_(_prefixes)))
                        _prefix_map = {pk: pn for pk, pn in psr.all()}
                        for n in _still_missing:
                            if "_" in n:
                                pfx, act = n.split("_", 1)
                                if pfx in _prefix_map:
                                    _label_map[n] = f"{_prefix_map[pfx]} ({act.replace('_', ' ').title()})…"

    tool_results: list[dict] = []
    _held_for_approval: list[dict] = []  # tools held by the approval gate (not executed)
    from src.services.chat_cancel import is_cancelled as _is_cancelled_tools

    # Parallel read-tier precompute (#229). Read-tier tools (file_read, board_read,
    # knowledge_search, github/gitlab read, …) have no side effects, no approval gate,
    # and no file delivery, so their order is irrelevant and they can run concurrently.
    # We compute them up-front via asyncio.gather and the sequential loop below then
    # consumes the cached result at the single _run_single_tool site — AFTER all gates
    # pass — so every event, ordering, and gating decision is byte-identical to the
    # sequential path; only the side-effect-free awaits overlap. Flag-gated; default off
    # runs everything inline exactly as before. A result is only consumed post-gate, so
    # a cached call the loop later skips (gate fail) is simply discarded.
    _precomputed: dict[int, dict] = {}
    from src.core.config import get_settings as _gs_par
    if _gs_par().parallel_tool_calls_enabled and len(tool_calls) > 1:
        from src.services.agent_tools.risk import tool_risk_tier as _trt
        _read_idx = [
            _i for _i, _c in enumerate(tool_calls)
            if _c.get("name") and _trt(_c.get("name", "")) == "read"
            and is_tool_allowed(_c.get("name", ""), agent_enabled)
        ]
        if len(_read_idx) > 1:
            async def _precompute_one(_idx: int) -> tuple[int, dict]:
                _c = tool_calls[_idx]
                try:
                    _r = await _run_single_tool(
                        _c["name"], dict(_c.get("args", {})), chat_id,
                        agent_id, agent_name, parent_chat_id=parent_chat_id,
                    )
                    return _idx, _r
                except Exception as _exc:
                    return _idx, {"tool": _c.get("name"), "error": str(_exc)}
            _done = await asyncio.gather(*[_precompute_one(_i) for _i in _read_idx])
            _precomputed = {i: r for i, r in _done}

    for _call_idx, call in enumerate(tool_calls):
        # Pre-emptive cancel check (#223): stop between tools so a user cancel during a
        # multi-tool turn takes effect promptly instead of after the whole batch runs.
        try:
            if await _is_cancelled_tools(chat_id):
                logger.info("[tools] cancellation observed — halting remaining tool calls")
                break
        except Exception:
            pass
        name = call.get("name", "")
        args = dict(call.get("args", {}))
        if not name:
            continue
        # CLI providers (esp. Gemini) sometimes serialise their OWN native /
        # MCP function calls into the response text instead of executing them.
        # These leak into this parser as bogus tool_calls; failing them back
        # ("Unknown tool") fuels an endless resume loop. Drop them silently.
        if name.startswith("mcp__") or name in _CLI_INTERNAL_TOOLS:
            logger.info(f"[tools] ignoring leaked CLI-internal tool call {name!r}")
            continue
        # Authoritative gate (#222): when the agent is restricted (has a tool config),
        # EVERY tool must be in its enabled set (or always-allowed) — not just the
        # platform_executor builtins. None = unrestricted (no tools configured).
        if not is_tool_allowed(name, agent_enabled):
            logger.warning(f"[tools] agent {agent_id!r} called tool {name!r} not enabled for it — skipping")
            tool_results.append({"tool": name, "error": f"Tool '{name}' is not enabled for this agent."})
            continue
        # Validate declared required args (#214): a structured "missing required
        # argument" correction beats a deep executor failure. No-op for tools that
        # declare no schema.
        _arg_err = validate_tool_args(name, args)
        if _arg_err:
            logger.info(f"[tools] {name!r} arg validation: {_arg_err}")
            tool_results.append({"tool": name, "error": _arg_err})
            continue
        # Governance risk policy (#235): an operator can hard-deny a whole risk tier
        # (exec / external) for an unattended deployment. Always-allowed coordination
        # tools are exempt. Default config denies nothing → inert.
        if name not in _always_allowed():
            from src.core.config import get_settings as _gs_risk
            from src.services.agent_tools.risk import tool_denied_by_policy, tool_risk_tier, tool_requires_approval
            from src.services.tool_approvals import is_yolo as _is_yolo
            _gs = _gs_risk()
            if tool_denied_by_policy(name, _gs):
                logger.warning(f"[tools] {name!r} blocked by risk policy (tier={tool_risk_tier(name)})")
                tool_results.append({"tool": name, "error": f"Tool '{name}' ({tool_risk_tier(name)} tier) is blocked by the organization's risk policy."})
                continue
            # Human-in-the-loop approval (#235): hold the tool, record a pending
            # approval, and return a blocking result so the agent stops. A human
            # approves via the approvals API → the tool then runs + the chat resumes.
            # Skip if this exact pending call was already recorded (avoid dup on resume).
            # Bypass the gate when: per-chat YOLO is on (user opted out of the prompt),
            # or a prior "approve always (similar)" in this session already cleared a
            # call with the same command content.
            from src.services.tool_approvals import is_similar_approved as _is_similar_ok
            if (tool_requires_approval(name, _gs)
                    and not await _is_yolo(chat_id)
                    and not await _is_similar_ok(chat_id, name, args)):
                from src.services.tool_approvals import record_pending_approval
                _appr = await record_pending_approval(
                    chat_id=chat_id, message_id=message_id, agent_id=agent_id,
                    agent_name=agent_name, tool_name=name, tool_args=args,
                    tier=tool_risk_tier(name),
                )
                if _appr is not None:
                    _held_for_approval.append(call)
                    tool_results.append({"tool": name, "awaiting_approval": True, "data": (
                        f"⏸ Awaiting human approval to run '{name}' ({tool_risk_tier(name)} tier). "
                        f"A reviewer must approve it (approval id {_appr}). Do NOT retry — stop now "
                        "and end your turn; the action will run automatically once approved."
                    )})
                    continue
        # Repeated-failure breaker (model-agnostic anti-loop): if this EXACT tool call
        # (same name + args) has already failed repeatedly in this chat, refuse to run it
        # again. A weak model that ignores an error and re-emits the identical failing
        # call (e.g. gitlab_api action="create" over and over) can't wedge the turn.
        _fail_sig = None
        try:
            import hashlib as _hl
            from src.core.redis import get_redis as _gr
            _fail_sig = (f"toolfail:{chat_id}:{name}:"
                         f"{_hl.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:12]}")
            _fc = await _gr().get(_fail_sig)
            _fc = int(_fc) if _fc else 0
            if _fc >= 2:
                logger.warning("[tools] blocking repeated failing call %s in chat %s (failed %d×)", name, chat_id, _fc)
                call["_status"] = "failed"
                call["_error"] = "blocked: repeated identical failure"
                tool_results.append({"tool": name, "error": (
                    f"BLOCKED: you already called '{name}' with these exact arguments and it failed "
                    f"{_fc} times. Calling it again will fail the same way. Do something DIFFERENT: "
                    "use another tool/approach, or stop and report what you have. (To add/commit files "
                    "use git_local, not gitlab_api 'create'.)"
                )})
                continue
        except Exception:
            _fail_sig = None

        label = _label_map.get(name)

        if not label:
            formatted_name = name.replace("_", " ").title()
            label = f"{formatted_name}…"

        if name == "task_create" and args.get("title"):
            label = f"Create: {str(args['title'])[:60]}"
        elif name == "task_update" and args.get("task_id"):
            label = f"Update task…"
        elif name == "log_entry" and args.get("message"):
            label = f"Log: {str(args['message'])[:60]}"
        elif name == "read_url" and args.get("url"):
            label = f"Fetch: {str(args['url'])[:60]}"
        elif name == "issue_manage" and args.get("action") == "create" and args.get("title"):
            label = f"Issue: {str(args['title'])[:60]}"
        elif name == "issue_manage" and args.get("action") == "comment" and args.get("issue_id"):
            label = f"Comment on issue…"
        elif name == "issue_manage" and args.get("action") == "update" and args.get("issue_id"):
            label = f"Update issue…"
        await _ws_status(websocket, "executing_tool", name, label, pub_chat_id=_status_pub)

        # Emit action card event for PM/direct-chat tool calls (not sub-agent tasks)
        if _pm_group_id:
            await _broadcast(chat_id, {
                "type": "agent_action_start",
                "group_id": _pm_group_id,
                "message_id": message_id,
                "agent_name": agent_name or "Agent",
                "tool": name,
                "label": label.rstrip("…"),
            })

        step_id = str(uuid.uuid4())
        if task_id and parent_chat_id:
            async with AsyncSessionLocal() as db:
                step = TaskStep(
                    id=step_id,
                    task_id=task_id,
                    name=name,
                    label=label,
                    status="running",
                )
                db.add(step)
                await db.commit()

            step_start_event = {
                "type": "sub_agent_step_start",
                "task_id": task_id,
                "step_id": step_id,
                "step_name": name,
                "step_label": label,
            }
            await _broadcast(parent_chat_id, step_start_event)
            if chat_id != parent_chat_id:
                await _broadcast(chat_id, step_start_event)

        try:
            # Use the parallel-precomputed result for a read-tier call (#229); else
            # run it inline now. Identical result either way — reads have no side effects.
            if _call_idx in _precomputed:
                result = _precomputed[_call_idx]
            else:
                result = await _run_single_tool(name, args, chat_id, agent_id, agent_name, parent_chat_id=parent_chat_id)
            logger.info(f"[tools] executed {name} args={json.dumps(args)[:120]}")

            tool_errored = isinstance(result, dict) and "error" in result
            # Record the outcome on the call so tool_calls_detail can persist real
            # per-tool status — otherwise a failed tool reconstructs as "success" on
            # refresh (live shows red, refresh shows green).
            call["_status"] = "failed" if tool_errored else "success"
            if tool_errored:
                call["_error"] = str(result.get("error", ""))[:300]

            # Feed the repeated-failure breaker: count identical failures, clear on success.
            if _fail_sig:
                try:
                    from src.core.redis import get_redis as _gr2
                    _r = _gr2()
                    if tool_errored:
                        await _r.incr(_fail_sig)
                        await _r.expire(_fail_sig, 600)
                    else:
                        await _r.delete(_fail_sig)
                except Exception:
                    pass

            if task_id and parent_chat_id:
                async with AsyncSessionLocal() as db:
                    step = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
                    step_rec = step.scalar_one_or_none()
                    if step_rec:
                        step_rec.status = "failed" if tool_errored else "success"
                        if result is not None:
                            step_rec.result_data = result
                        if tool_errored:
                            step_rec.error = str(result.get("error", ""))[:500]
                        step_rec.completed_at = datetime.now(timezone.utc)
                        await db.commit()

                step_done_ok = {
                    "type": "sub_agent_step_done",
                    "task_id": task_id,
                    "step_id": step_id,
                    "status": "failed" if tool_errored else "success",
                }
                await _broadcast(parent_chat_id, step_done_ok)
                if chat_id != parent_chat_id:
                    await _broadcast(chat_id, step_done_ok)

            if _pm_group_id:
                await _broadcast(chat_id, {
                    "type": "agent_action_done",
                    "group_id": _pm_group_id,
                    "tool": name,
                    "status": "failed" if tool_errored else "success",
                    "error": str(result.get("error", ""))[:200] if tool_errored else None,
                })

            if result is not None:
                tool_results.append(result)

            # Guaranteed delivery: a successful file_write writes to a throwaway
            # container path that the user never sees. Auto-register it as a downloadable
            # ChatFile so the output always reaches the Files panel even if the agent
            # never calls attach_file. (Skip if the agent already attached it explicitly.)
            if name == "file_write" and not tool_errored and isinstance(result, dict):
                _wpath = ((result.get("data") or {}) if isinstance(result.get("data"), dict) else {}).get("path")
                if _wpath:
                    try:
                        _deliv = await auto_deliver_written_file(chat_id, parent_chat_id, str(_wpath))
                    except Exception as _dexc:
                        _deliv = None
                        logger.warning(f"[tools] auto-deliver of {_wpath} failed: {_dexc}")
                    if _deliv:
                        _updated = _deliv.get("updated")
                        logger.info(f"[tools] auto-{'updated' if _updated else 'delivered'} written file '{_deliv['name']}'")
                        tool_results.append({"tool": "file_deliver", "data": {
                            "delivered": True, "name": _deliv["name"],
                            "download_url": _deliv["download_url"], "size_bytes": _deliv["size_bytes"],
                            "message": (
                                f"'{_deliv['name']}' is saved in the workspace and shown in the Files panel. "
                                + ("It already existed and was UPDATED in place — the panel shows one entry, not a copy. "
                                   if _updated else "")
                                + "It is already delivered; do NOT write the same file again unless its contents must change."
                            ),
                        }})
        except Exception as exc:
            logger.warning(f"[tools] {name} failed: {exc}")
            call["_status"] = "failed"
            call["_error"] = str(exc)[:300]

            if task_id and parent_chat_id:
                async with AsyncSessionLocal() as db:
                    step = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
                    step_rec = step.scalar_one_or_none()
                    if step_rec:
                        step_rec.status = "failed"
                        step_rec.error = str(exc)[:500]
                        step_rec.completed_at = datetime.now(timezone.utc)
                        await db.commit()

                step_done_fail = {
                    "type": "sub_agent_step_done",
                    "task_id": task_id,
                    "step_id": step_id,
                    "status": "failed",
                    "error": str(exc)[:200],
                }
                await _broadcast(parent_chat_id, step_done_fail)
                if chat_id != parent_chat_id:
                    await _broadcast(chat_id, step_done_fail)

            if _pm_group_id:
                await _broadcast(chat_id, {
                    "type": "agent_action_done",
                    "group_id": _pm_group_id,
                    "tool": name,
                    "status": "failed",
                    "error": str(exc)[:200],
                })

    await _ws_status(websocket, "idle", pub_chat_id=_status_pub)
    # FULL list of executed tool calls (name+args). This drives the "Agent · N
    # actions" card reconstruction on refresh, so it must include log_entry +
    # task_*/goal_* — usage stats apply their own filter via billable_call_count().
    # Exclude tools held for approval — they were NOT executed this turn, so they must
    # not reconstruct as an "Agent · N actions · done" card on refresh (that's the job
    # of the approval card; it ran via the approve flow, not here).
    _held_ids = {id(c) for c in _held_for_approval}
    counted = [
        {
            "name": c.get("name", ""),
            "args": c.get("args", {}),
            # Persist real per-tool outcome so the action card reconstructs with the
            # correct status/color on refresh (matches the live agent_action_done).
            "status": c.get("_status", "success"),
            **({"error": c["_error"]} if c.get("_error") else {}),
        }
        for c in tool_calls
        if c.get("name") and id(c) not in _held_ids
    ]
    # Prepend any inline ```file: deliveries (handled before the tool_calls fence) so the
    # resume sees them alongside the JSON tool results.
    return clean_text, _file_deliveries + tool_results, counted, True, None


# Coordination tools that should NOT count toward the user-facing "tool calls" usage
# metric (they're orchestration bookkeeping, not work the user pays attention to).
_STATS_HIDDEN_PREFIXES = ("task_", "goal_", "milestone_")
_STATS_HIDDEN_NAMES = {"log_entry"}


def billable_call_count(calls: list[dict]) -> int:
    """Count tool calls for usage stats, excluding coordination bookkeeping
    (log_entry, task_*/goal_*/milestone_*). The action-card list keeps everything;
    only the numeric metric is filtered."""
    n = 0
    for c in calls or []:
        name = c.get("name", "")
        if not name or name in _STATS_HIDDEN_NAMES or name.startswith(_STATS_HIDDEN_PREFIXES):
            continue
        n += 1
    return n
