"""In-process executor auto-discovery and single-tool dispatch."""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, desc, func
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat, Message
from src.models.project import Project
from src.models.agent import Agent
from src.models.skill import Skill
from src.services.agent_tools.task_helpers import _resolve_agent_id, _bubble_complete_parent
from src.services.agent_tools.skill_runner import _resolve_skill_tool, _run_skill_tool
from src.services.agent_tools import tool_subprocess as _tool_subprocess

logger = logging.getLogger(__name__)

# Org/user env-var injection for in-process executors. They read os.getenv, so
# we overlay resolved values via a task-local contextvars wrapper around
# os.environ (services/env_context) — no global lock, no cross-call leakage.
# Subprocess (venv) tools get env passed directly. Dep-free tools with no
# declared env_vars skip resolution entirely.


async def _resolve_tool_env(name: str, chat_id, agent_id) -> dict:
    """Resolve a tool's declared env_vars from org/user storage (org-first).
    Returns {} when the tool declares none or nothing is configured."""
    try:
        from src.services import env_vars as _env_vars
        return await _env_vars.resolve_for_chat(name, chat_id, agent_id)
    except Exception as exc:  # noqa: BLE001 — credentials must never break dispatch
        logger.debug("[tool_executor] env resolve failed for %s: %s", name, exc)
        return {}


_SEEDS_ROOT = Path(__file__).parent.parent.parent / "seeds"
_executor_registry: dict[str, object] | None = None


async def _walk_chat_to_root(chat_id: str, db) -> str:
    """Return the root chat id by walking Chat.parent_chat_id upward. A top-level
    chat is its own root. Cycle-safe."""
    cur = chat_id
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        parent = (await db.execute(
            select(Chat.parent_chat_id).where(Chat.id == cur)
        )).scalar_one_or_none()
        if not parent:
            return cur
        cur = parent
    return cur  # last valid id if a cycle is hit


async def _enforce_root_spawn_caps(chat_id: str, db) -> str | None:
    """Per-ROOT-conversation spawn backstop. The per-parent fan-out cap only bounds
    siblings under one parent; a recursive loop evades it by spawning across many
    sub-chats. This counts spawns against the ROOT chat (cumulative + rate, in Redis)
    so one runaway conversation cannot create unbounded sub-agents.

    Returns a user/agent-facing message string when a cap is hit (caller returns it
    as the tool result so the orchestrator stops), or None to allow the spawn.
    Fails OPEN if Redis is unavailable — a backstop must never wedge normal work.
    """
    from src.core.config import get_settings as _gs
    s = _gs()
    if s.max_subagents_per_root <= 0 and s.max_spawn_rate_per_root <= 0:
        return None
    try:
        from src.core.redis import get_redis
        redis = get_redis()
        root = await _walk_chat_to_root(chat_id, db)

        if s.max_spawn_rate_per_root > 0:
            window = max(1, s.max_spawn_rate_window_seconds)
            rk = f"spawn_rate:{root}"
            cur = await redis.incr(rk)
            await redis.expire(rk, window)
            if cur > s.max_spawn_rate_per_root:
                logger.warning(
                    "[task_create] root spawn-rate cap hit (root=%s, %d/%ds > %d) — rejecting",
                    root, cur, window, s.max_spawn_rate_per_root,
                )
                return (
                    f"Spawn-rate limit reached: this conversation has spawned {cur} sub-agents "
                    f"in the last {window}s (max {s.max_spawn_rate_per_root}). This usually means a "
                    "runaway delegation loop. Do NOT spawn more — finish with the results you have "
                    "and end your turn with <final/>."
                )

        if s.max_subagents_per_root > 0:
            tk = f"spawn_total:{root}"
            tot = await redis.incr(tk)
            await redis.expire(tk, 86400)  # per-conversation-day ceiling; resets after 24h idle
            if tot > s.max_subagents_per_root:
                logger.warning(
                    "[task_create] root cumulative spawn cap hit (root=%s, %d > %d) — rejecting",
                    root, tot, s.max_subagents_per_root,
                )
                return (
                    f"Sub-agent limit reached: this conversation has already spawned {tot} sub-agents "
                    f"(max {s.max_subagents_per_root}). This is a hard safety cap against runaway "
                    "delegation. Do NOT spawn more — consolidate the remaining work or report what you "
                    "have, and end your turn with <final/>."
                )
    except Exception as exc:
        logger.warning("[task_create] root spawn-cap check unavailable (%s) — allowing", exc)
        return None
    return None


def _build_executor_registry() -> dict[str, object]:
    """Scan seeds/tools and seeds/skills for executor.py files and cache their execute()."""
    import importlib.util
    registry: dict[str, object] = {}
    for base in (_SEEDS_ROOT / "tools", _SEEDS_ROOT / "skills"):
        for source in ("builtin", "custom"):
            src_dir = base / source
            if not src_dir.exists():
                continue
            for item_dir in sorted(src_dir.iterdir()):
                if not item_dir.is_dir():
                    continue
                exec_path = item_dir / "executor.py"
                if not exec_path.exists():
                    continue
                key = item_dir.name
                try:
                    spec = importlib.util.spec_from_file_location(f"_exec_{key}", exec_path)
                    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                    spec.loader.exec_module(mod)  # type: ignore[union-attr]
                    if callable(getattr(mod, "execute", None)):
                        registry[key] = mod.execute
                        logger.debug(f"[tools] executor loaded: {key}")
                except Exception as exc:
                    logger.warning(f"[tools] failed to load executor for '{key}': {exc}")
    return registry


def _get_executor(name: str):
    global _executor_registry
    if _executor_registry is None:
        _executor_registry = _build_executor_registry()
    return _executor_registry.get(name)


# Platform tools implemented inline in _run_single_tool (no executor.py). Kept as a
# constant so is_executable_tool() and the dispatch agree on what's "real".
_INLINE_TOOLS: frozenset[str] = frozenset({
    "task_create", "task_update", "task_delete", "spawn_subagent",
    "plan_create", "plan_step_complete", "plan_complete",
    "board_read", "log_entry", "attach_file",
    "goal_create", "goal_update", "milestone_add", "milestone_status", "goal_read",
})


def is_executable_tool(key: str) -> bool:
    """True if a tool key resolves to a real handler (GitLab #226).

    Mirrors the dispatch resolution order in `_run_single_tool`: inline platform
    tool, local-exec proxy tool, an `executor.py` (tools or skills), a subprocess
    (requirements.txt) tool, or a skill `<key>_<cmd>` tool. "Phantom" tools that
    ship only `tool.json` + `TOOL.md` (no handler) return False so the catalog can
    avoid advertising a tool that would just answer "Unknown tool".
    """
    if not key:
        return False
    if key in _INLINE_TOOLS:
        return True
    try:
        from src.services.agent_tools import local_exec
        if key in local_exec.LOCAL_TOOLS:
            return True
    except Exception:
        pass
    if _get_executor(key) is not None:
        return True
    try:
        from src.services.agent_tools import tool_subprocess
        if tool_subprocess.has_requirements(key):
            return True
    except Exception:
        pass
    try:
        from src.services.agent_tools.skill_runner import _resolve_skill_tool
        if _resolve_skill_tool(key) is not None:
            return True
    except Exception:
        pass
    return False


def _parse_tool_calls(raw_json: str) -> list[dict] | None:
    """Parse tool calls JSON tolerantly.

    Handles:
    - A JSON array: [{"name": ..., "args": ...}, ...]
    - A single bare object: {"name": ..., "args": ...}
    - Multiple bare objects emitted without array brackets (LLM formatting quirk)
    Returns None if no valid objects could be extracted.
    """
    raw_json = raw_json.strip()
    # Strip leading "tool_calls" keyword if LLM wrote it inline (e.g. "tool_calls [{...}]")
    if raw_json.lower().startswith('tool_calls'):
        raw_json = raw_json[len('tool_calls'):].lstrip()
    # Fast path: valid JSON array or single object
    try:
        obj = json.loads(raw_json)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)] or None
        return None
    except json.JSONDecodeError:
        pass
    # If raw_json looks like a (possibly truncated) array, strip the leading [
    # so raw_decode can extract individual complete objects from a partial array.
    # This handles max_tokens truncation mid-fence gracefully.
    scan = raw_json
    if scan.startswith('['):
        scan = scan[1:].lstrip()
    # Fallback: scan out multiple objects using raw_decode (handles "Extra data" case)
    calls: list[dict] = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(scan):
        # skip whitespace and stray commas between objects
        while pos < len(scan) and scan[pos] in ' \t\n\r,':
            pos += 1
        if pos >= len(scan):
            break
        try:
            obj, end = decoder.raw_decode(scan, pos)
            if isinstance(obj, dict):
                calls.append(obj)
            pos = end
        except json.JSONDecodeError:
            break
    return calls or None


def _titles_overlap(a: str, b: str) -> bool:
    """Heuristic: do two task titles describe the same work? True when one normalized
    title is a prefix/substring of the other (≥15 shared leading chars). Catches the
    paraphrase loop ('Ejecutar ps aux y reportar resultado' vs '...resultado completo')
    without false-matching genuinely different tasks."""
    def _norm(s: str) -> str:
        return " ".join((s or "").lower().split())
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(short) >= 15 and long.startswith(short)


_RETRIEVAL_VERB_RE = re.compile(
    r'\b(find|locate|retrieve|look\s+for|search\s+for|check\s+for|fetch|'
    r'buscar|encontrar|localizar|recuperar)\b', re.IGNORECASE)
_RETRIEVAL_OBJECT_RE = re.compile(
    r'\b(files?|outputs?|attachments?|cards?|documents?|results?|'
    r'archivos?|ficheros?)\b', re.IGNORECASE)
# Imperative creation/modification verbs (whole words only — NOT "created"/"produced",
# which describe PRIOR work being retrieved, the exact case we want to block).
_CREATION_VERB_RE = re.compile(
    r'\b(create|build|generate|write|implement|fix|refactor|make|design|'
    r'crear|generar|escribir|construir)\b', re.IGNORECASE)


def _is_pure_retrieval_delegation(title: str, desc: str) -> bool:
    """Heuristic: is this delegated task just 'go find/retrieve the file(s) a previous
    agent produced'? Such tasks are pointless — produced files are tracked + delivered —
    and were a real spin loop (orchestrator spawns 'Local Operator' to hunt the disk).
    Conservative: requires BOTH a retrieval verb AND a file-ish object, and no imperative
    creation verb, so genuine specialist work ('find the bug', 'build + save a report')
    is not blocked. Word-boundary matching so 'created/produced by' doesn't read as 'create'."""
    blob = f"{title} {desc}"
    if not _RETRIEVAL_VERB_RE.search(blob):
        return False
    if not _RETRIEVAL_OBJECT_RE.search(blob):
        return False
    if _CREATION_VERB_RE.search(blob):
        return False
    return True


async def _resolve_local_bridge(chat_id: str, parent_chat_id: str | None):
    """Find a registered local-exec bridge for this chat or any ancestor chat.

    Sub-agents run in sub-chats (their own chat_id) whose ancestry leads back to the CLI
    chat that registered the bridge. Walk up Chat.parent_chat_id until a bridge is found.
    """
    from src.services.agent_tools import local_exec
    b = local_exec.get_bridge(chat_id)
    if b is not None:
        return b
    cur = parent_chat_id
    seen: set[str] = set()
    if cur is None:
        # discover the immediate parent if not supplied
        async with AsyncSessionLocal() as db:
            row = await db.execute(select(Chat.parent_chat_id).where(Chat.id == chat_id))
            cur = row.scalar_one_or_none()
    async with AsyncSessionLocal() as db:
        while cur and cur not in seen and len(seen) < 8:
            seen.add(cur)
            b = local_exec.get_bridge(cur)
            if b is not None:
                return b
            row = await db.execute(select(Chat.parent_chat_id).where(Chat.id == cur))
            cur = row.scalar_one_or_none()
    return None


async def _attach_file(
    args: dict,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
    parent_chat_id: str | None,
) -> dict:
    """Register a file the agent produced as a downloadable chat attachment.

    Web/container chats: read the file from the container filesystem.
    CLI local-exec chats: read it back from the user's host through the local bridge.
    Either way the bytes are stored in upload_dir and a ChatFile row is created so the
    file shows in the Files panel and is downloadable in one click. A `file_created`
    event is broadcast (to the root chat, and the sub-chat if different) for live refresh.
    """
    import mimetypes
    from pathlib import Path
    from src.core.config import get_settings
    from src.core.pubsub import broadcast
    from src.models.chat_file import ChatFile
    from src.models.chat import ChatParticipant

    path_str = (args.get("path") or "").strip()
    if not path_str:
        return {"tool": "attach_file", "error": "path is required"}
    display_name = (args.get("name") or Path(path_str).name or "file").strip()

    # Resolve the root chat (files hang off the conversation root) and an owner user_id.
    root_id = chat_id
    owner_id: str | None = None
    async with AsyncSessionLocal() as db:
        seen: set[str] = set()
        cur: str | None = chat_id
        while cur and cur not in seen:
            seen.add(cur)
            row = (await db.execute(select(Chat).where(Chat.id == cur))).scalar_one_or_none()
            if not row:
                break
            if row.user_id and owner_id is None:
                owner_id = row.user_id
            if not row.parent_chat_id:
                root_id = row.id
                if row.user_id:
                    owner_id = row.user_id
                break
            cur = row.parent_chat_id
        if not owner_id:
            part = (await db.execute(
                select(ChatParticipant.user_id)
                .where(ChatParticipant.chat_id == root_id)
                .limit(1)
            )).scalar_one_or_none()
            owner_id = part
    if not owner_id:
        return {"tool": "attach_file", "error": "Could not resolve a file owner for this chat"}

    # Acquire the file bytes — via the local-exec bridge if this chat proxies to a CLI host,
    # otherwise straight from the container filesystem.
    bridge = await _resolve_local_bridge(chat_id, parent_chat_id)
    content_bytes: bytes | None = None
    local_path: str | None = None
    if bridge is not None:
        local_path = path_str
        try:
            raw = await bridge.run("file_read", {"path": path_str})
        except Exception as exc:
            return {"tool": "attach_file", "error": f"Could not read local file: {exc}"}
        data = (raw or {}).get("data") if isinstance(raw, dict) else None
        text = data.get("content") if isinstance(data, dict) else None
        if isinstance(text, str):
            content_bytes = text.encode("utf-8", errors="replace")
    else:
        p = Path(path_str)
        if not p.exists() or not p.is_file():
            return {"tool": "attach_file", "error": f"File not found: {path_str}"}
        try:
            content_bytes = p.read_bytes()
        except Exception as exc:
            return {"tool": "attach_file", "error": str(exc)}

    if content_bytes is None:
        # Local binary/unreadable file — surface the path so the user can still find it.
        if local_path:
            return {"tool": "attach_file", "data": {
                "attached": False,
                "local_path": local_path,
                "message": f"The file is on your machine at {local_path}. It couldn't be read "
                           "as text to copy into the conversation (likely binary).",
            }}
        return {"tool": "attach_file", "error": "Could not read file content"}

    stored = await _store_and_register_file(
        chat_id, root_id, owner_id, display_name, content_bytes, suffix_hint=path_str
    )
    if "error" in stored:
        return {"tool": "attach_file", "error": stored["error"]}
    result = {
        "attached": True,
        "file_id": stored["file_id"],
        "name": display_name,
        "size_bytes": len(content_bytes),
        "download_url": stored["download_url"],
        "message": f"Attached '{display_name}' to the conversation — downloadable from the Files panel.",
    }
    if local_path:
        result["local_path"] = local_path
    return {"tool": "attach_file", "data": result}


async def _resolve_file_owner(chat_id: str) -> tuple[str, str | None]:
    """Walk up the chat's parent chain to find the conversation root + an owner user_id.
    Files hang off the root chat so a sub-agent's output lands in the user's Files panel."""
    from src.models.chat import ChatParticipant
    root_id = chat_id
    owner_id: str | None = None
    async with AsyncSessionLocal() as db:
        seen: set[str] = set()
        cur: str | None = chat_id
        while cur and cur not in seen:
            seen.add(cur)
            row = (await db.execute(select(Chat).where(Chat.id == cur))).scalar_one_or_none()
            if not row:
                break
            if row.user_id and owner_id is None:
                owner_id = row.user_id
            if not row.parent_chat_id:
                root_id = row.id
                if row.user_id:
                    owner_id = row.user_id
                break
            cur = row.parent_chat_id
        if not owner_id:
            owner_id = (await db.execute(
                select(ChatParticipant.user_id).where(ChatParticipant.chat_id == root_id).limit(1)
            )).scalar_one_or_none()
    return root_id, owner_id


async def _store_and_register_file(
    chat_id: str,
    root_id: str,
    owner_id: str,
    display_name: str,
    content_bytes: bytes,
    suffix_hint: str = "",
) -> dict:
    """Persist bytes under upload_dir, create a ChatFile row on the conversation root,
    and broadcast file_created. Shared by attach_file, the inline file fence, and the
    file_write auto-deliver hook. Returns {file_id, download_url} or {error}."""
    import mimetypes
    from pathlib import Path
    from src.core.config import get_settings
    from src.core.pubsub import broadcast
    from src.models.chat_file import ChatFile

    settings = get_settings()
    upload_root = Path(settings.upload_dir) / root_id
    try:
        upload_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"error": f"Failed to prepare attachment storage: {exc}"}
    ext = Path(display_name).suffix or Path(suffix_hint).suffix
    stored_name = f"{uuid.uuid4()}{ext}"
    try:
        (upload_root / stored_name).write_bytes(content_bytes)
    except Exception as exc:
        return {"error": f"Failed to store attachment: {exc}"}

    content_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    file_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        cf = ChatFile(
            id=file_id,
            chat_id=chat_id,
            root_chat_id=root_id,
            user_id=owner_id,
            original_filename=display_name,
            stored_filename=stored_name,
            content_type=content_type,
            size_bytes=len(content_bytes),
        )
        db.add(cf)
        await db.commit()
        await db.refresh(cf)
        created_iso = cf.created_at.isoformat() if cf.created_at else None

    file_payload = {
        "id": file_id, "name": display_name, "size": len(content_bytes),
        "content_type": content_type, "chat_id": chat_id, "created_at": created_iso,
    }
    await broadcast(root_id, {"type": "file_created", "file": file_payload})
    if root_id != chat_id:
        await broadcast(chat_id, {"type": "file_created", "file": file_payload})
    return {"file_id": file_id, "download_url": f"/api/chats/{chat_id}/files/{file_id}/content"}


async def deliver_inline_file(
    chat_id: str, parent_chat_id: str | None, display_name: str, content: str,
) -> dict:
    """Write+deliver a file straight from inline text content (the ```file:PATH fence).

    Bypasses JSON tool-call escaping entirely — weak models can't reliably embed a 10KB
    HTML/code string inside a JSON arg without producing invalid JSON, which silently
    dropped the deliverable. The raw fence is just a code block, so it always survives.
    """
    content_bytes = content.encode("utf-8", errors="replace")
    root_id, owner_id = await _resolve_file_owner(chat_id)
    if not owner_id:
        return {"error": "Could not resolve a file owner for this chat"}
    stored = await _store_and_register_file(chat_id, root_id, owner_id, display_name, content_bytes)
    if "error" in stored:
        return stored
    return {
        "delivered": True,
        "file_id": stored["file_id"],
        "name": display_name,
        "size_bytes": len(content_bytes),
        "download_url": stored["download_url"],
    }


async def auto_deliver_written_file(
    chat_id: str, parent_chat_id: str | None, path_str: str,
) -> dict | None:
    """After a successful file_write, register the written file as a downloadable
    ChatFile so the output reaches the user even if the agent forgets attach_file.
    Returns the delivery info, or None if the file couldn't be read/delivered."""
    from pathlib import Path
    # Local-exec chats: file lives on the user's host → read back via the bridge.
    bridge = await _resolve_local_bridge(chat_id, parent_chat_id)
    content_bytes: bytes | None = None
    if bridge is not None:
        try:
            raw = await bridge.run("file_read", {"path": path_str})
            data = (raw or {}).get("data") if isinstance(raw, dict) else None
            text = data.get("content") if isinstance(data, dict) else None
            if isinstance(text, str):
                content_bytes = text.encode("utf-8", errors="replace")
        except Exception:
            return None
    else:
        p = Path(path_str)
        try:
            if not p.exists() or not p.is_file():
                return None
            content_bytes = p.read_bytes()
        except Exception:
            return None
    if content_bytes is None:
        return None
    root_id, owner_id = await _resolve_file_owner(chat_id)
    if not owner_id:
        return None
    display_name = Path(path_str).name or "file"
    stored = await _store_and_register_file(
        chat_id, root_id, owner_id, display_name, content_bytes, suffix_hint=path_str
    )
    if "error" in stored:
        return None
    return {"file_id": stored["file_id"], "name": display_name,
            "download_url": stored["download_url"], "size_bytes": len(content_bytes)}


async def _run_single_tool(
    name: str,
    args: dict,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
    parent_chat_id: str | None = None,
) -> dict | None:
    """Execute one tool call. Returns result data for read tools, None for write-only."""
    from src.models.task import Task
    from src.models.agent_log import AgentLog
    from src.core.pubsub import broadcast
    from src.services.agent_tools import local_exec

    # Local execution: if this chat (or an ancestor — for sub-agents running in sub-chats)
    # is driven by a CLI client that opted into local exec, route filesystem/shell builtins
    # to that host instead of running them in-container.
    if name in local_exec.LOCAL_TOOLS:
        bridge = await _resolve_local_bridge(chat_id, parent_chat_id)
        if bridge is not None:
            raw = await bridge.run(name, dict(args))
            if raw is None:
                return None
            return {"tool": name, **raw}

    if name == "task_create":
        # Dedup delegated sub-agent tasks. Weak orchestrators (and watchdog-nudged
        # resumes) re-spawn for one request — often PARAPHRASING the title each turn
        # ("Ejecutar ps aux" → "...y reportar resultado" → "...completo") and routing
        # to the SAME agent. We block when, for the current user turn, an equivalent
        # delegated task already exists, matched by ANY of:
        #   • same assigned agent that has already run (in_progress/completed), or
        #   • same/overlapping title, or same description.
        # Same-batch parallel decomposition is preserved: those tasks are all still
        # `pending` (not in_progress/completed) and use distinct titles. Scope is
        # reset by the next user message.
        _is_delegation = bool(args.get("assigned_agent_id") or args.get("agent_persona"))
        _dup_title = (args.get("title") or "").strip()
        _dup_desc = (args.get("description") or "").strip()

        # Over-delegation guard: refuse to spawn a sub-agent whose only job is to FIND /
        # RETRIEVE / LOCATE files or output a previous agent produced. Files are tracked
        # and already in the user's Files panel; spinning up a "Local Operator" to hunt
        # the disk for them is the exact loop that wedged real chats. The orchestrator
        # should use file_find/file_list/board_read directly, or just recognize delivery.
        if _is_delegation and _is_pure_retrieval_delegation(_dup_title, _dup_desc):
            logger.info("[task_create] blocked pure-retrieval delegation '%s' in chat %s", _dup_title, chat_id)
            return {"tool": "task_create", "data": (
                "Do NOT delegate file/output retrieval to a sub-agent. Any file a prior task "
                "produced is already delivered to the user (Files panel) and tracked. If you "
                "genuinely need to inspect the filesystem, call `file_find`/`file_list` yourself "
                "in a tool_calls fence — don't spawn an agent for it. If the work is already done, "
                "confirm to the user and end with <final/>."
            )}

        if _is_delegation and (_dup_title or _dup_desc):
            async with AsyncSessionLocal() as _ddb:
                _new_agent = await _resolve_agent_id(args.get("assigned_agent_id"), _ddb)
                _last_user = (await _ddb.execute(
                    select(Message.created_at).where(
                        Message.chat_id == chat_id,
                        Message.role == "user",
                        Message.excluded.is_(False),
                    ).order_by(desc(Message.created_at)).limit(1)
                )).scalar_one_or_none()
                if _last_user is not None:
                    _recent = (await _ddb.execute(
                        select(Task).where(
                            Task.chat_id == chat_id,
                            Task.assigned_agent_id.isnot(None),
                            Task.created_at > _last_user,
                            Task.status.in_(["pending", "queued", "in_progress", "completed"]),
                        ).order_by(desc(Task.created_at)).limit(25)
                    )).scalars().all()
                    _hit = None
                    for _t in _recent:
                        # same agent that already ran this turn → don't pile on another
                        if _new_agent and _t.assigned_agent_id == _new_agent \
                                and _t.status in ("in_progress", "completed"):
                            _hit = _t
                            break
                        if _dup_title and _titles_overlap(_dup_title, _t.title or ""):
                            _hit = _t
                            break
                        if _dup_desc and (_t.description or "").strip() == _dup_desc:
                            _hit = _t
                            break
                    if _hit is not None:
                        logger.info(
                            "[task_create] dedup — '%s' overlaps existing %s task this turn in chat %s",
                            _dup_title or _dup_desc, _hit.status, chat_id,
                        )
                        return {"tool": "task_create", "data": (
                            f"A sub-agent for this request is already {_hit.status} "
                            f"('{(_hit.title or '')[:60]}') — NOT spawning a duplicate. Use its "
                            "result (it runs in its own sub-chat / memory); do not redo the work "
                            "or re-spawn. End your turn now with <final/>."
                        )}

        async with AsyncSessionLocal() as db:
            resolved_agent_id = await _resolve_agent_id(args.get("assigned_agent_id"), db)

            # Fan-out cap: bound concurrently-active sibling tasks under one parent (a runaway
            # orchestrator once spawned 72 in a single turn). Uses the CALLING agent's
            # per-agent `max_subagents` (configured in the agent builder); falls back to the
            # platform default config.max_tasks_per_parent. 0 = unlimited.
            from src.core.config import get_settings as _get_settings
            _cap = None
            if agent_id:
                _cap = (await db.execute(
                    select(Agent.max_subagents).where(Agent.id == agent_id)
                )).scalar_one_or_none()
            if not _cap:
                _cap = _get_settings().max_tasks_per_parent
            if _cap and _cap > 0:
                _pid = args.get("parent_id")
                _cq = select(func.count()).select_from(Task).where(
                    Task.chat_id == chat_id,
                    Task.status.in_(["pending", "queued", "in_progress"]),
                )
                _cq = _cq.where(Task.parent_id == _pid) if _pid else _cq.where(Task.parent_id.is_(None))
                _sib = (await db.execute(_cq)).scalar() or 0
                if _sib >= _cap:
                    logger.warning(
                        "[task_create] fan-out cap %d reached (chat=%s parent=%s, active=%d) — rejecting",
                        _cap, chat_id, _pid, _sib,
                    )
                    return {"tool": "task_create", "data": (
                        f"Fan-out limit reached: {_sib} sibling tasks are already active under this "
                        f"parent (max {_cap}). Do NOT spawn more — wait for the running tasks to finish "
                        "and use their results, or consolidate the remaining work into fewer tasks. "
                        "End your turn now with <final/>."
                    )}

            # Per-ROOT spawn backstop (cumulative + rate) — catches recursive loops
            # that evade the per-parent cap by spreading across many sub-chats.
            _root_msg = await _enforce_root_spawn_caps(chat_id, db)
            if _root_msg:
                return {"tool": "task_create", "data": _root_msg}

            task_org_id: str | None = None
            if agent_id:
                r_ag0 = await db.execute(select(Agent).where(Agent.id == agent_id))
                calling_ag = r_ag0.scalar_one_or_none()
                if calling_ag:
                    task_org_id = calling_ag.org_id
            if not task_org_id:
                r_ch0 = await db.execute(select(Chat).where(Chat.id == chat_id))
                ch0 = r_ch0.scalar_one_or_none()
                if ch0 and ch0.project_id:
                    r_pr0 = await db.execute(select(Project).where(Project.id == ch0.project_id))
                    pr0 = r_pr0.unique().scalar_one_or_none()
                    if pr0:
                        task_org_id = pr0.org_id
                if not task_org_id and ch0 and ch0.user_id:
                    from src.models.org import OrgMember
                    r_om = await db.execute(
                        select(OrgMember).where(OrgMember.user_id == ch0.user_id).limit(1)
                    )
                    om = r_om.scalar_one_or_none()
                    if om:
                        task_org_id = om.org_id

            persona = args.get("agent_persona")
            if persona and not resolved_agent_id:
                r_chat = await db.execute(select(Chat).where(Chat.id == chat_id))
                parent_chat_rec = r_chat.scalar_one_or_none()
                parent_env: dict = {}
                org_id_for_agent: str | None = None
                if parent_chat_rec and parent_chat_rec.agent_id:
                    r_ag = await db.execute(select(Agent).where(Agent.id == parent_chat_rec.agent_id))
                    parent_ag = r_ag.scalar_one_or_none()
                    if parent_ag:
                        org_id_for_agent = parent_ag.org_id
                        parent_env = parent_ag.env_vars or {}
                if not org_id_for_agent and agent_id:
                    r_om2 = await db.execute(select(Agent).where(Agent.id == agent_id).limit(1))
                    fb_ag = r_om2.scalar_one_or_none()
                    org_id_for_agent = fb_ag.org_id if fb_ag else None
                if not org_id_for_agent:
                    org_id_for_agent = task_org_id

                # Per-license agent quota (no-op in OSS): an on-demand persona
                # agent counts too — refuse gracefully if the org is at its limit.
                from src.services.billing_limits import agent_quota_message
                _q = await agent_quota_message(org_id_for_agent)
                if _q:
                    return {"tool": "task_create", "data": (
                        f"{_q} Cannot create the on-demand agent for this task. "
                        "Reuse an existing agent or free up agent slots."
                    )}

                merged_env = {**parent_env, **(persona.get("env_vars") or {})}

                new_agent = Agent(
                    id=str(uuid.uuid4()),
                    org_id=org_id_for_agent,
                    name=persona.get("name", "Ad-hoc Agent"),
                    description=persona.get("description"),
                    agent_type=persona.get("agent_type", "custom"),
                    system_prompt=persona.get("system_prompt"),
                    skills=persona.get("skills", []),
                    env_vars=merged_env,
                    tools=persona.get("tools", []),
                    mcps=persona.get("mcps", []),
                    is_active=True,
                )
                db.add(new_agent)
                await db.flush()
                resolved_agent_id = new_agent.id
                logger.info(f"[task_create] created on-demand agent '{new_agent.name}' ({new_agent.id})")

            last_msg_result = await db.execute(
                select(Message.id)
                .where(Message.chat_id == chat_id)
                .order_by(desc(Message.created_at))
                .limit(1)
            )
            last_msg_id = last_msg_result.scalar_one_or_none()

            model_profile_id = args.get("model_profile_id") or None

            task = Task(
                id=str(uuid.uuid4()),
                org_id=task_org_id,
                chat_id=chat_id,
                parent_id=args.get("parent_id"),
                title=args.get("title", "Untitled"),
                description=args.get("description"),
                assigned_agent_id=resolved_agent_id,
                checklist=args.get("checklist", []),
                position=args.get("position", 0),
                status="pending",
                priority=args.get("priority", "medium"),
                blocked_by=args.get("blocked_by", []),
                created_after_message_id=last_msg_id,
                continue_chat_id=args.get("continue_chat_id"),
                model_profile_id=model_profile_id,
                retry_policy=args.get("retry_policy") or None,
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            now_iso = task.created_at.isoformat()
            resolved_name: str | None = None
            if task.assigned_agent_id:
                r = await db.execute(select(Agent).where(Agent.id == task.assigned_agent_id))
                ag = r.scalar_one_or_none()
                if ag:
                    resolved_name = ag.name
        await broadcast(chat_id, {"type": "task_created", "task": {
            "id": task.id, "chat_id": task.chat_id,
            "parent_id": task.parent_id, "position": task.position,
            "title": task.title, "description": task.description,
            "output": None, "status": task.status,
            "priority": task.priority,
            "blocked_by": task.blocked_by or [],
            "assigned_agent_id": task.assigned_agent_id,
            "assigned_agent_name": resolved_name,
            "model_override": None, "provider_chain_id": None,
            "checklist": task.checklist or [], "sub_chat_id": None,
            "created_at": now_iso, "updated_at": now_iso, "completed_at": None,
        }})

    elif name == "spawn_subagent":
        # Virtual tool: lets any provider spawn a sub-agent via the standard
        # tool_calls fence (Codex also reaches it as an MCP tool). Routes through
        # the shared helper → delegated task → Nexora's sub-agent engine. Returns
        # a confirmation so the orchestrator gets feedback instead of stalling.
        from src.services.sub_agent.spawn import spawn_subagent_task
        msg = await spawn_subagent_task(args, chat_id, agent_id, agent_name)
        return {"tool": "spawn_subagent", "data": msg}

    elif name == "task_update":
        task_id = args.get("task_id")
        if not task_id:
            return None
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one_or_none()
            if not task:
                return None
            # Allow cross-chat task management within the same project.
            # The calling chat must belong to the same project as the task's chat.
            if task.chat_id != chat_id:
                r_caller = await db.execute(select(Chat).where(Chat.id == chat_id))
                caller_chat = r_caller.scalar_one_or_none()
                r_task_chat = await db.execute(select(Chat).where(Chat.id == task.chat_id))
                task_chat = r_task_chat.scalar_one_or_none()
                if not (caller_chat and task_chat and caller_chat.project_id and caller_chat.project_id == task_chat.project_id):
                    return None
            for field in ("title", "description", "status", "output"):
                if field in args:
                    setattr(task, field, args[field])
            if "assigned_agent_id" in args:
                task.assigned_agent_id = await _resolve_agent_id(args["assigned_agent_id"], db)
            if "checklist" in args:
                task.checklist = args["checklist"]
            if "priority" in args:
                task.priority = args["priority"]
            if "blocked_by" in args:
                task.blocked_by = args["blocked_by"]
            if "retry_policy" in args and isinstance(args["retry_policy"], dict):
                task.retry_policy = args["retry_policy"]
            if "agent_overrides" in args and isinstance(args["agent_overrides"], dict):
                incoming: dict = args["agent_overrides"]
                # Validate capability grants: calling agent can only grant what it has
                if agent_id and ("additional_skills" in incoming or "additional_tools" in incoming):
                    r_caller = await db.execute(select(Agent).where(Agent.id == agent_id))
                    caller_ag = r_caller.scalar_one_or_none()
                    if caller_ag:
                        allowed_skills = set(caller_ag.skills or [])
                        allowed_tools = set(caller_ag.tools or [])
                        if "additional_skills" in incoming:
                            incoming = {**incoming, "additional_skills": [
                                s for s in (incoming["additional_skills"] or []) if s in allowed_skills
                            ]}
                        if "additional_tools" in incoming:
                            incoming = {**incoming, "additional_tools": [
                                t for t in (incoming["additional_tools"] or []) if t in allowed_tools
                            ]}
                existing = task.agent_overrides or {}
                task.agent_overrides = {**existing, **incoming}
            if task.status == "completed" and not task.completed_at:
                task.completed_at = datetime.now(timezone.utc)
            # Clear sub_chat_id when explicitly reset to pending so dispatcher can re-dispatch.
            if args.get("status") == "pending":
                task.sub_chat_id = None
                task.completed_at = None
            await db.commit()
            await db.refresh(task)
            resolved_name = None
            if task.assigned_agent_id:
                r2 = await db.execute(select(Agent).where(Agent.id == task.assigned_agent_id))
                ag = r2.scalar_one_or_none()
                if ag:
                    resolved_name = ag.name
        await broadcast(chat_id, {"type": "task_updated", "task": {
            "id": task.id, "chat_id": task.chat_id,
            "parent_id": task.parent_id, "position": task.position,
            "title": task.title, "description": task.description,
            "output": task.output, "status": task.status,
            "priority": getattr(task, "priority", "medium") or "medium",
            "blocked_by": getattr(task, "blocked_by", []) or [],
            "assigned_agent_id": task.assigned_agent_id,
            "assigned_agent_name": resolved_name,
            "model_override": task.model_override,
            "provider_chain_id": task.provider_chain_id,
            "checklist": task.checklist or [], "sub_chat_id": task.sub_chat_id,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }})
        if task.status in ("completed", "failed") and task.parent_id:
            asyncio.create_task(_bubble_complete_parent(task.parent_id))

    elif name == "task_delete":
        task_id = args.get("task_id")
        if not task_id:
            return None
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one_or_none()
            if task:
                allowed = task.chat_id == chat_id
                if not allowed:
                    # Allow cross-chat deletion within the same project
                    r_caller = await db.execute(select(Chat).where(Chat.id == chat_id))
                    caller_chat = r_caller.scalar_one_or_none()
                    r_task_chat = await db.execute(select(Chat).where(Chat.id == task.chat_id))
                    task_chat = r_task_chat.scalar_one_or_none()
                    allowed = bool(caller_chat and task_chat and caller_chat.project_id and caller_chat.project_id == task_chat.project_id)
                if allowed:
                    await db.delete(task)
                    await db.commit()
        await broadcast(chat_id, {"type": "task_deleted", "task_id": task_id})

    elif name == "plan_create":
        from src.models.plan import Plan, PlanStep
        from src.models.agent import Agent as _Agent
        async with AsyncSessionLocal() as db:
            plan_org_id: str | None = None
            if agent_id:
                r_ag = await db.execute(select(_Agent).where(_Agent.id == agent_id))
                _ag = r_ag.scalar_one_or_none()
                if _ag:
                    plan_org_id = _ag.org_id
            plan = Plan(
                id=str(uuid.uuid4()),
                org_id=plan_org_id,
                chat_id=chat_id,
                title=args.get("title", "Project Plan"),
                status="active",
            )
            db.add(plan)
            await db.flush()
            steps_data = args.get("steps") or []
            plan_steps = []
            for i, s in enumerate(steps_data):
                step = PlanStep(
                    id=str(uuid.uuid4()),
                    plan_id=plan.id,
                    position=i,
                    title=s.get("title", f"Step {i+1}"),
                    description=s.get("description"),
                    status="pending",
                )
                db.add(step)
                plan_steps.append(step)
            await db.commit()
            await db.refresh(plan)
            for ps in plan_steps:
                await db.refresh(ps)
        plan_payload = {
            "id": plan.id,
            "chat_id": plan.chat_id,
            "title": plan.title,
            "status": plan.status,
            "steps": [
                {"id": s.id, "plan_id": s.plan_id, "position": s.position,
                 "title": s.title, "description": s.description,
                 "status": s.status, "note": s.note, "task_id": s.task_id}
                for s in plan_steps
            ],
            "created_at": plan.created_at.isoformat(),
        }
        await broadcast(chat_id, {"type": "plan_created", "plan": plan_payload})
        return {"tool": "plan_create", "data": {"plan_id": plan.id, "steps": len(plan_steps)}}

    elif name == "plan_step_complete":
        from src.models.plan import Plan, PlanStep
        from datetime import timezone
        step_id = args.get("step_id")
        note = args.get("note", "")
        if not step_id:
            return {"tool": "plan_step_complete", "error": "step_id is required"}
        async with AsyncSessionLocal() as db:
            rs = await db.execute(select(PlanStep).where(PlanStep.id == step_id))
            step = rs.scalar_one_or_none()
            if not step:
                return {"tool": "plan_step_complete", "error": f"Step {step_id} not found"}
            step.status = "done"
            step.note = note
            await db.flush()
            rp = await db.execute(select(Plan).where(Plan.id == step.plan_id))
            plan = rp.scalar_one_or_none()
            plan_auto_completed = False
            if plan and plan.status == "active":
                rall = await db.execute(select(PlanStep).where(PlanStep.plan_id == plan.id))
                all_steps = rall.scalars().all()
                if all(s.status in ("done", "failed", "skipped") for s in all_steps):
                    plan.status = "completed"
                    plan.completed_at = datetime.now(timezone.utc)
                    plan_auto_completed = True
            await db.commit()
            await db.refresh(step)
        step_payload = {
            "id": step.id, "plan_id": step.plan_id, "position": step.position,
            "title": step.title, "status": step.status, "note": step.note,
        }
        await broadcast(chat_id, {"type": "plan_step_updated", "step": step_payload})
        if plan_auto_completed:
            await broadcast(chat_id, {"type": "plan_completed", "plan_id": step.plan_id})
        return {"tool": "plan_step_complete", "data": {"step_id": step_id, "status": "done"}}

    elif name == "plan_complete":
        from src.models.plan import Plan, PlanStep
        from datetime import timezone
        plan_id = args.get("plan_id")
        if not plan_id:
            return {"tool": "plan_complete", "error": "plan_id is required"}
        async with AsyncSessionLocal() as db:
            rp = await db.execute(select(Plan).where(Plan.id == plan_id))
            plan = rp.scalar_one_or_none()
            if not plan:
                return {"tool": "plan_complete", "error": f"Plan {plan_id} not found"}
            plan.status = "completed"
            plan.completed_at = datetime.now(timezone.utc)
            await db.commit()
        await broadcast(chat_id, {"type": "plan_completed", "plan_id": plan_id})
        return {"tool": "plan_complete", "data": {"plan_id": plan_id, "status": "completed"}}

    elif name in ("goal_create", "goal_update", "milestone_add", "milestone_status", "goal_read"):
        # Autonomy layer (#232): durable objectives the agent can read + advance.
        from src.models.goal import Goal, Milestone
        from src.models.agent import Agent as _Agent
        from src.services.goals import recompute_goal_progress, set_milestone_status as _set_ms

        async def _agent_org(db) -> str | None:
            # Resolve the org from any available source — not just the agent (a chat
            # may run without a bound agent, or the agent may predate org wiring):
            # agent.org_id → chat/ancestor project's org → chat owner's active org.
            if agent_id:
                o = (await db.execute(select(_Agent.org_id).where(_Agent.id == agent_id))).scalar_one_or_none()
                if o:
                    return o
            from src.models.chat import Chat as _Chat
            from src.models.project import Project as _Project
            from src.models.user import User as _User
            cur = chat_id
            seen: set[str] = set()
            while cur and cur not in seen:
                seen.add(cur)
                c = (await db.execute(select(_Chat).where(_Chat.id == cur))).scalar_one_or_none()
                if not c:
                    break
                if c.project_id:
                    po = (await db.execute(select(_Project.org_id).where(_Project.id == c.project_id))).scalar_one_or_none()
                    if po:
                        return po
                if c.user_id:
                    uo = (await db.execute(select(_User.active_org_id).where(_User.id == c.user_id))).scalar_one_or_none()
                    if uo:
                        return uo
                cur = c.parent_chat_id
            return None

        if name == "goal_create":
            title = (args.get("title") or "").strip()
            if not title:
                return {"tool": name, "error": "title is required"}
            async with AsyncSessionLocal() as db:
                org_id = await _agent_org(db)
                if not org_id:
                    return {"tool": name, "error": "no org context for goal_create"}
                goal = Goal(
                    id=str(uuid.uuid4()), org_id=org_id, title=title,
                    description=args.get("description"),
                    success_criteria=args.get("success_criteria"),
                    parent_goal_id=args.get("parent_goal_id"),
                    owner_agent_id=args.get("owner_agent_id") or agent_id,
                    priority=int(args.get("priority") or 0),
                )
                db.add(goal)
                await db.flush()
                ms_in = args.get("milestones") or []
                for i, m in enumerate(ms_in):
                    if isinstance(m, str):
                        m = {"title": m}
                    db.add(Milestone(
                        id=str(uuid.uuid4()), goal_id=goal.id, position=i,
                        title=(m.get("title") or f"Milestone {i+1}"),
                        description=m.get("description"),
                        success_criteria=m.get("success_criteria"),
                    ))
                await db.commit()
                gid = goal.id
                await recompute_goal_progress(db, gid)
            await broadcast(chat_id, {"type": "goal_created", "goal_id": gid, "title": title})
            return {"tool": name, "data": {"goal_id": gid, "title": title, "milestones": len(ms_in)}}

        if name == "goal_update":
            gid = args.get("goal_id")
            if not gid:
                return {"tool": name, "error": "goal_id is required"}
            async with AsyncSessionLocal() as db:
                org_id = await _agent_org(db)
                g = (await db.execute(select(Goal).where(Goal.id == gid))).scalar_one_or_none()
                if not g or (org_id and g.org_id != org_id):
                    return {"tool": name, "error": f"goal {gid} not found"}
                for f in ("title", "description", "success_criteria", "status"):
                    if args.get(f) is not None:
                        setattr(g, f, args[f])
                if args.get("priority") is not None:
                    g.priority = int(args["priority"])
                await db.commit()
            await broadcast(chat_id, {"type": "goal_updated", "goal_id": gid})
            return {"tool": name, "data": {"goal_id": gid, "updated": True}}

        if name == "milestone_add":
            gid = args.get("goal_id")
            title = (args.get("title") or "").strip()
            if not gid or not title:
                return {"tool": name, "error": "goal_id and title are required"}
            async with AsyncSessionLocal() as db:
                org_id = await _agent_org(db)
                g = (await db.execute(select(Goal).where(Goal.id == gid))).scalar_one_or_none()
                if not g or (org_id and g.org_id != org_id):
                    return {"tool": name, "error": f"goal {gid} not found"}
                _pos = (await db.execute(select(func.count(Milestone.id)).where(Milestone.goal_id == gid))).scalar() or 0
                m = Milestone(
                    id=str(uuid.uuid4()), goal_id=gid, position=int(args.get("position") or _pos),
                    title=title, description=args.get("description"),
                    success_criteria=args.get("success_criteria"),
                )
                db.add(m)
                await db.commit()
                mid = m.id
                await recompute_goal_progress(db, gid)
            await broadcast(chat_id, {"type": "goal_updated", "goal_id": gid})
            return {"tool": name, "data": {"milestone_id": mid, "goal_id": gid}}

        if name == "milestone_status":
            mid = args.get("milestone_id")
            status = (args.get("status") or "").strip().lower().replace(" ", "_")
            # Accept common synonyms the model reaches for (e.g. "completed") so it
            # doesn't fail + waste a retry turn.
            _status_alias = {
                "completed": "done", "complete": "done", "completado": "done", "completada": "done",
                "hecho": "done", "finished": "done", "in-progress": "in_progress",
                "inprogress": "in_progress", "en_progreso": "in_progress", "doing": "in_progress",
                "todo": "pending", "pendiente": "pending", "blocked": "failed", "skip": "skipped",
            }
            status = _status_alias.get(status, status)
            if not mid or status not in ("pending", "in_progress", "done", "failed", "skipped"):
                return {"tool": name, "error": "milestone_id and a valid status are required (pending|in_progress|done|failed|skipped)"}
            async with AsyncSessionLocal() as db:
                org_id = await _agent_org(db)
                m = (await db.execute(select(Milestone).where(Milestone.id == mid))).scalar_one_or_none()
                if not m:
                    return {"tool": name, "error": f"milestone {mid} not found"}
                g = (await db.execute(select(Goal).where(Goal.id == m.goal_id))).scalar_one_or_none()
                if org_id and (not g or g.org_id != org_id):
                    return {"tool": name, "error": f"milestone {mid} not found"}
                m = await _set_ms(db, mid, status)
                gid = m.goal_id
            await broadcast(chat_id, {"type": "goal_updated", "goal_id": gid})
            return {"tool": name, "data": {"milestone_id": mid, "status": status}}

        if name == "goal_read":
            gid = args.get("goal_id")
            async with AsyncSessionLocal() as db:
                org_id = await _agent_org(db)
                if not org_id:
                    return {"tool": name, "error": "no org context"}
                if gid:
                    g = (await db.execute(select(Goal).where(Goal.id == gid, Goal.org_id == org_id))).scalar_one_or_none()
                    if not g:
                        return {"tool": name, "error": f"goal {gid} not found"}
                    ms = (await db.execute(select(Milestone).where(Milestone.goal_id == gid).order_by(Milestone.position))).scalars().all()
                    return {"tool": name, "data": {
                        "id": g.id, "title": g.title, "status": g.status, "progress": g.progress,
                        "success_criteria": g.success_criteria,
                        "milestones": [{"id": m.id, "title": m.title, "status": m.status} for m in ms],
                    }}
                rows = (await db.execute(
                    select(Goal).where(Goal.org_id == org_id, Goal.status.in_(["active", "blocked"]))
                    .order_by(Goal.priority.desc()).limit(50)
                )).scalars().all()
                return {"tool": name, "data": {"goals": [
                    {"id": g.id, "title": g.title, "status": g.status, "progress": g.progress} for g in rows
                ]}}

    elif name == "board_read":
        project_id = args.get("project_id")
        filter_agent = args.get("filter_by_agent")  # agent_id string
        filter_status = args.get("filter_by_status")  # comma-separated statuses
        include_done = bool(args.get("include_completed", False))
        _columns = ["pending", "queued", "in_progress", "paused", "completed", "failed"]
        _active_statuses = ["pending", "queued", "in_progress", "paused"]
        board: dict[str, list] = {col: [] for col in _columns}
        async with AsyncSessionLocal() as db:
            if project_id:
                chat_r = await db.execute(select(Chat).where(Chat.project_id == project_id))
                chat_ids = [c.id for c in chat_r.scalars().all()]
            else:
                r_ch = await db.execute(select(Chat).where(Chat.id == chat_id))
                ch = r_ch.scalar_one_or_none()
                project_id = ch.project_id if ch else None
                if project_id:
                    chat_r = await db.execute(select(Chat).where(Chat.project_id == project_id))
                    chat_ids = [c.id for c in chat_r.scalars().all()]
                else:
                    chat_ids = [chat_id]
            task_q = (
                select(Task)
                .where(Task.chat_id.in_(chat_ids), Task.parent_id == None)  # noqa: E711
                .order_by(Task.position, Task.created_at)
            )
            if filter_agent:
                task_q = task_q.where(Task.assigned_agent_id == filter_agent)
            if filter_status:
                allowed = [s.strip() for s in filter_status.split(",")]
                task_q = task_q.where(Task.status.in_(allowed))
            elif not include_done:
                # Default: skip completed/failed — board can have thousands of historical tasks
                task_q = task_q.where(Task.status.in_(_active_statuses))
            task_r = await db.execute(task_q)
            tasks_all = task_r.scalars().all()

            # Batch-load agent names
            _agent_ids = {t.assigned_agent_id for t in tasks_all if t.assigned_agent_id}
            _agent_names: dict[str, str] = {}
            if _agent_ids:
                from src.models.agent import Agent as _Agent
                ag_r = await db.execute(select(_Agent).where(_Agent.id.in_(_agent_ids)))
                for _ag in ag_r.scalars().all():
                    _agent_names[_ag.id] = _ag.name

            include_details = bool(args.get("include_details", False))
            for t in tasks_all:
                col = t.status if t.status in _columns else "pending"
                entry: dict = {
                    "id": t.id,
                    "title": t.title,
                    "agent": _agent_names.get(t.assigned_agent_id or ""),
                    "status": t.status,
                }
                if include_details:
                    entry["description"] = t.description
                    entry["priority"] = getattr(t, "priority", "medium") or "medium"
                    entry["blocked_by"] = getattr(t, "blocked_by", []) or []
                    entry["checklist"] = t.checklist or []
                board[col].append(entry)
        return {"tool": "board_read", "data": board}

    elif name == "log_entry":
        async with AsyncSessionLocal() as db:
            entry = AgentLog(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                task_id=args.get("task_id"),
                agent_id=agent_id,
                agent_name=agent_name or args.get("agent_name"),
                level=args.get("level", "info"),
                message=args.get("message", ""),
                data=args.get("data"),
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
        log_payload = {
            "id": entry.id, "chat_id": entry.chat_id,
            "task_id": entry.task_id, "agent_id": entry.agent_id,
            "agent_name": entry.agent_name, "level": entry.level,
            "message": entry.message, "data": entry.data,
            "created_at": entry.created_at.isoformat(),
        }
        await broadcast(chat_id, {"type": "log_entry", "log": log_payload})
        # Propagate to parent chat so the main conversation UI sees it live
        if parent_chat_id and parent_chat_id != chat_id:
            await broadcast(parent_chat_id, {"type": "log_entry", "log": log_payload})

    elif name == "attach_file":
        return await _attach_file(args, chat_id, agent_id, agent_name, parent_chat_id)

    # Isolated-venv tool: a seed dir with a requirements.txt runs as a subprocess
    # in its own per-pack venv (dependency isolation). Checked BEFORE the
    # in-process registry — such executors do lazy third-party imports that fail
    # in the base env, so they're never in the in-process registry anyway.
    elif _tool_subprocess.has_requirements(name):
        _env = await _resolve_tool_env(name, chat_id, agent_id)
        raw = await _tool_subprocess.run(name, args, chat_id, agent_id, agent_name, env=_env)
        if raw is None:
            return None
        return {"tool": name, **raw}

    # Auto-discovered in-process executor (executor.py in seed tool/skill directory)
    elif executor_fn := _get_executor(name):
        _env = await _resolve_tool_env(name, chat_id, agent_id)
        try:
            if _env:
                from src.services import env_context
                with env_context.use_env(_env):
                    raw = await executor_fn(args, chat_id, agent_id, agent_name)
            else:
                raw = await executor_fn(args, chat_id, agent_id, agent_name)
        except Exception as exc:
            return {"tool": name, "error": str(exc)}
        if raw is None:
            return None
        return {"tool": name, **raw}  # raw is {"data": ...} or {"error": ...}

    # Subprocess skill scripts (*_tool.py convention)
    elif _resolve_skill_tool(name) is not None:
        return await _run_skill_tool(name, args, chat_id, agent_id, agent_name)

    else:
        logger.warning(f"Unknown tool name: {name}")
        return {"tool": name, "error": f"Unknown tool '{name}'. This tool is not available."}

    return None
