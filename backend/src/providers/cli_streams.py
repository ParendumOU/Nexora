"""OAuth CLI streaming backends — Claude, Gemini, and Codex subprocess invocations."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import AsyncIterator

from src.core.config import get_settings
from src.core.cli_rate_limiter import check_cli_rate_limit
from src.models.provider import Provider
from src.providers.exceptions import ProviderError

logger = logging.getLogger(__name__)

# Sentinel prefix used to pass metadata through the string-based stream protocol.
# The null byte ensures no real LLM text can collide with it.
_METADATA_PREFIX = "\x00META:"

# Gemini spawn-directive fence: ```nexora_spawn\n<JSON array|object>\n```
# Gemini has no native sub-agent tool and its MCP path is unverified in
# non-interactive mode, so it emits sub-agent spawns as a fenced directive that
# we parse out of its final response (see seeds/prompts/cli_fence_subagent.md).
_SPAWN_FENCE_RE = re.compile(r"```nexora_spawn\s*\n([\s\S]*?)\n?```", re.IGNORECASE)


def _extract_spawn_directives(text: str) -> tuple[str, list[dict]]:
    """Pull ```nexora_spawn fenced directives out of text.

    Returns (text_with_fences_removed, [directive, ...]). Each directive is a
    dict like {title, task, skills?, tools?}. Malformed fences are dropped.
    """
    directives: list[dict] = []

    def _collect(m: "re.Match") -> str:
        body = (m.group(1) or "").strip()
        try:
            obj = json.loads(body)
        except Exception:
            return ""
        items = obj if isinstance(obj, list) else [obj]
        for d in items:
            if isinstance(d, dict) and (d.get("title") or d.get("task")):
                directives.append(d)
        return ""

    cleaned = _SPAWN_FENCE_RE.sub(_collect, text)
    return cleaned.strip(), directives


def _get_default_model(provider_key: str) -> str:
    from src.seeds.loader import get_provider
    pdef = get_provider(provider_key)
    return (pdef.get("default_model") or "") if pdef else ""


def _get_cli_command(provider_key: str) -> str:
    from src.seeds.loader import get_provider
    pdef = get_provider(provider_key)
    return (pdef.get("cli_command") or provider_key) if pdef else provider_key


def _metadata_event(data: dict) -> str:
    return f"{_METADATA_PREFIX}{json.dumps(data, separators=(',', ':'))}"


def _cli_env(home_dir: str) -> dict:
    """Build environment for CLI subprocess with isolated HOME."""
    import os
    return {
        **os.environ,
        "HOME": home_dir,
        "TERM": "xterm-256color",
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
    }


def _extract_text_from_content(content) -> str:
    """Safely extract text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


async def _iter_subprocess_lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    pending = b""
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace").strip()
    if pending:
        yield pending.decode("utf-8", errors="replace").strip()


def _build_cli_prompt(messages: list[dict], system_prompt: str | None = None) -> tuple[str, str]:
    """Return (system_context, user_prompt) suitable for passing to CLI tools.

    Conversation history is folded into system_context so the CLI receives
    the new user turn as the direct prompt (cleaner than a concatenated blob).
    """
    if not messages:
        return system_prompt or "", ""

    last = messages[-1]
    history = messages[:-1] if last["role"] == "user" else messages
    user_prompt = _extract_text_from_content(last.get("content", "")) if last["role"] == "user" else ""

    system_parts: list[str] = []
    if system_prompt:
        system_parts.append(system_prompt)

    if history:
        system_parts.append("Prior conversation:")
        for msg in history:
            role = "Human" if msg["role"] == "user" else "Assistant"
            system_parts.append(f"{role}: {_extract_text_from_content(msg.get('content', ''))}")

    return "\n\n".join(system_parts), user_prompt


async def _stream_claude_cli(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    """Invoke the `claude` CLI as a subprocess for OAuth-authenticated accounts.

    Claude OAuth tokens (sk-ant-oat01-*) are issued by Claude.ai and are NOT
    valid as Anthropic API keys.  The only correct way to use them is through
    the `claude` CLI itself with HOME pointing to the credentials directory.

    Note: --dangerously-skip-permissions cannot be used as root (Docker default).
    We use --verbose instead, which enables stream-json output without requiring
    elevated permission bypass.  The stream format differs slightly from the
    --dangerously-skip-permissions path; this parser handles both.
    """
    import os
    import shutil
    import tempfile

    from src.core.config import get_settings
    from src.providers.cli_observability import claude_hooks, registry

    home_dir = provider.auth_path
    if not home_dir or not Path(home_dir).exists():
        raise ProviderError("Claude OAuth: auth directory not found — re-authenticate in Settings")

    _user_id = str(kw.get("user_id") or "")
    _org_id = str(kw.get("org_id") or "")
    if _user_id or _org_id:
        _allowed, _reason = await check_cli_rate_limit(_user_id, _org_id)
        if not _allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail=_reason)

    model = kw.get("model_override") or provider.model_name or _get_default_model("claude")
    system_ctx, user_prompt = _build_cli_prompt(messages, kw.get("system_prompt"))

    mcp_cfg = {
        "mcpServers": {
            "nexora": {
                "command": "python",
                "args": ["/app/src/mcp_server.py"],
                "env": {
                    "NX_CHAT_ID":    kw.get("chat_id") or "",
                    "NX_AGENT_ID":   kw.get("agent_id") or "",
                    "NX_AGENT_NAME": kw.get("agent_name") or "",
                },
            }
        }
    }
    fd, mcp_config_path = tempfile.mkstemp(suffix=".json", prefix="nx_mcp_")
    # Isolated working directory: limits filesystem exposure for native tools and
    # hosts the project-level .claude/settings.json that streams hooks to Nexora.
    work_dir = tempfile.mkdtemp(prefix="nx_claude_")
    run_token = registry.new_token()
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(mcp_cfg, f)

        # Stream Claude Code's internal sub-agent activity back into this chat.
        await registry.register(
            run_token,
            chat_id=kw.get("chat_id") or "",
            agent_id=kw.get("agent_id") or "",
            agent_name=kw.get("agent_name") or "",
            provider="claude",
            org_id=kw.get("org_id"),
            model=model,
            account_name=provider.name,
        )
        ingest_url = f"{get_settings().cli_hook_ingest_url.rstrip('/')}/api/cli-hooks/claude"
        claude_hooks.write_settings(work_dir, ingest_url, run_token)

        cmd = [
            _get_cli_command("claude"), "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--model", model,
            "--tools", "default",
        ]
        if get_settings().allow_cli_bypass_permissions:
            cmd.extend(["--permission-mode", "bypassPermissions"])
        cmd.extend([
            "--mcp-config", mcp_config_path,
            "--strict-mcp-config",
        ])
        if system_ctx:
            cmd += ["--system-prompt", system_ctx]
        cmd.append(user_prompt)

        # IS_SANDBOX=1 lets bypassPermissions run as root (Docker default user).
        env = {**_cli_env(home_dir), "IS_SANDBOX": "1"}
        meta: dict = {"provider": "claude", "model": model}

        logger.info(f"Claude CLI subprocess: HOME={home_dir} model={model} cwd={work_dir}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=work_dir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        yielded = False
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                evt = data.get("type")

                if evt == "assistant":
                    msg = data.get("message", {})
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yielded = True
                                yield text
                    # Don't extract tokens here — assistant.usage.output_tokens is
                    # partial (first chunk only). Use result.usage for correct totals.

                elif evt == "result":
                    if data.get("session_id"):
                        meta["session_id"] = data["session_id"]
                    if data.get("total_cost_usd") is not None:
                        meta["cost_usd"] = data["total_cost_usd"]
                    elif data.get("cost_usd") is not None:
                        meta["cost_usd"] = data["cost_usd"]
                    if data.get("duration_ms"):
                        meta["duration_ms"] = data["duration_ms"]
                    # result.usage has correct final token counts (vs assistant event which is partial)
                    result_usage = data.get("usage", {})
                    if result_usage:
                        meta["usage"] = {
                            "input_tokens":  result_usage.get("input_tokens", 0),
                            "output_tokens": result_usage.get("output_tokens", 0),
                        }
                    if not yielded:
                        text = data.get("result", "")
                        if text and text != "undefined":
                            yield text

            except json.JSONDecodeError:
                pass

        await proc.wait()
        if proc.returncode != 0:
            stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
            logger.error(f"Claude CLI exit {proc.returncode}: {stderr_text[:500]}")
            if not yielded:
                raise ProviderError(f"Claude CLI error (exit {proc.returncode}): {stderr_text[:300]}")

    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"Claude CLI subprocess error: {e}")
    finally:
        try:
            os.unlink(mcp_config_path)
        except Exception:
            pass
        shutil.rmtree(work_dir, ignore_errors=True)
        await registry.revoke(run_token)

    yield _metadata_event(meta)


async def _stream_gemini_cli(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    """Invoke the `gemini` CLI as a subprocess for OAuth-authenticated accounts.

    Gemini OAuth credentials (~/.gemini/oauth_creds.json) are Google OAuth2
    tokens that the CLI manages automatically (including refresh).  Running the
    CLI with HOME pointing to the credentials directory is the recommended path.
    """
    home_dir = provider.auth_path
    if not home_dir or not Path(home_dir).exists():
        raise ProviderError("Gemini OAuth: auth directory not found — re-authenticate in Settings")

    _user_id = str(kw.get("user_id") or "")
    _org_id = str(kw.get("org_id") or "")
    if _user_id or _org_id:
        _allowed, _reason = await check_cli_rate_limit(_user_id, _org_id)
        if not _allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail=_reason)

    import tempfile, shutil
    from src.core.config import get_settings
    from src.providers.cli_observability import gemini_hooks, registry
    model = kw.get("model_override") or provider.model_name or _get_default_model("gemini")
    meta: dict = {"provider": "gemini", "model": model}

    chat_id = kw.get("chat_id") or ""
    run_token = registry.new_token()

    # Gemini CLI reads GEMINI.md from cwd as system instructions (like CLAUDE.md).
    # Write the platform context there so the model gets full system prompt support
    # without mixing it into --prompt (which caused <final/> output-only behaviour).
    _msgs = messages if messages else []
    system_content: str = ""
    if _msgs and _msgs[0].get("role") == "system":
        system_content = _extract_text_from_content(_msgs[0].get("content", ""))
        _msgs = _msgs[1:]

    # Build conversation history + user prompt
    parts = []
    for m in _msgs[:-1]:
        role = "Human" if m["role"] == "user" else "Assistant"
        parts.append(f"{role}: {_extract_text_from_content(m.get('content', ''))}")
    user_prompt = _extract_text_from_content(_msgs[-1].get("content", "")) if _msgs else ""
    history_prefix = "\n".join(parts) + "\n\n" if parts else ""
    prompt_arg = f"{history_prefix}Human: {user_prompt}"

    tmpdir = tempfile.mkdtemp(prefix="nexora_gemini_")
    try:
        if system_content:
            Path(tmpdir).joinpath("GEMINI.md").write_text(system_content)

        # Stream Gemini's tool calls into Nexora as an ephemeral tool timeline.
        if chat_id:
            await registry.register(
                run_token, chat_id=chat_id,
                agent_id=kw.get("agent_id") or "", agent_name=kw.get("agent_name") or "",
                provider="gemini", org_id=kw.get("org_id"), model=model, account_name=provider.name,
            )
            ingest_url = f"{get_settings().cli_hook_ingest_url.rstrip('/')}/api/cli-hooks/gemini"
            gemini_hooks.write_settings(tmpdir, ingest_url, run_token)

        cmd = [
            _get_cli_command("gemini"),
            "--model", model,
            "--skip-trust",
            "--output-format", "json",
        ]
        if get_settings().allow_cli_bypass_permissions:
            cmd.append("--yolo")
        cmd.extend(["--prompt", prompt_arg])

        env = {
            **_cli_env(home_dir),
            "GEMINI_CLI_TRUST_WORKSPACE": "true",
        }

        logger.info(f"Gemini CLI subprocess: HOME={home_dir} model={model}")

        _GEMINI_NOISE = {
            "yolo mode is enabled",
            "all tool calls will be automatically approved",
            "256-color support not detected",
            "true color",
            "true color (24-bit)",
            "better visual experience",
            "ripgrep is not available",
            "using a terminal with at least 256",
            "cli_hook_relay.py",
        }

        def _clean_gemini_stderr(raw: str) -> str:
            lines = [l for l in raw.splitlines() if not any(n in l.lower() for n in _GEMINI_NOISE)]
            return "\n".join(lines).strip()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir,
            env=env,
        )

        stdout_bytes, stderr_bytes = await proc.communicate()
        output = stdout_bytes.decode("utf-8", errors="replace").strip()

        if not output:
            err = _clean_gemini_stderr(stderr_bytes.decode("utf-8", errors="replace"))
            raise ProviderError(f"Gemini CLI error: {err[:300]}")

        try:
            data = json.loads(output)
            text = data.get("response", "") or ""
            stats = data.get("stats", {})
            for _model_key, _model_stats in stats.get("models", {}).items():
                tokens = _model_stats.get("tokens", {})
                if tokens:
                    meta["usage"] = {
                        "input_tokens": tokens.get("input", 0),
                        "output_tokens": tokens.get("candidates", 0),
                    }
                    break
            # Spawn any sub-agents Gemini requested via fenced directives, then
            # strip the fences from the user-visible text. The created tasks are
            # dispatched by the post-turn _run_delegated_tasks (stream.py/ws.py).
            if text and chat_id:
                cleaned, directives = _extract_spawn_directives(text)
                if directives:
                    from src.services.sub_agent.spawn import spawn_subagent_task
                    for d in directives:
                        try:
                            await spawn_subagent_task(
                                d, chat_id,
                                kw.get("agent_id") or None, kw.get("agent_name") or None,
                            )
                        except Exception as exc:
                            logger.warning(f"[gemini-spawn] directive failed: {exc}")
                    text = cleaned
            # Gemini returns response:"" (often with an INVALID_STREAM error) when
            # a turn produced only tool calls / no final text. NEVER fall back to
            # yielding `output` — that dumps the raw stats+error JSON into the chat.
            if not text:
                gerr = data.get("error")
                if gerr:
                    logger.warning(f"[gemini] empty response, error={str(gerr)[:200]}")
            if text:
                yield text
        except (json.JSONDecodeError, AttributeError):
            # Not the expected JSON envelope — treat as plain model text.
            yield output

    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"Gemini CLI subprocess error: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        # Close the tool-timeline card (no-op on the frontend if no tool fired).
        if chat_id:
            try:
                from src.core.pubsub import broadcast as _bc
                await _bc(chat_id, {
                    "type": "sub_agent_done", "task_id": run_token,
                    "agent_name": model, "output": "", "failed": False,
                })
            except Exception:
                pass
            await registry.revoke(run_token)

    yield _metadata_event(meta)


def _write_codex_mcp_config(config_path: str, chat_id: str, agent_id: str, agent_name: str) -> None:
    """Write (or merge into) a Codex config.toml with the session-specific MCP server entry."""
    import os as _os

    existing_lines: list[str] = []
    if _os.path.exists(config_path):
        with open(config_path, "r", errors="replace") as f:
            existing_lines = f.readlines()

    filtered: list[str] = []
    skip = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("[mcp_servers.nexora") or stripped.startswith("[projects."):
            skip = True
        elif stripped.startswith("[") and skip:
            skip = False
        if not skip:
            filtered.append(line)

    def _q(v: str) -> str:
        return v.replace("\\", "\\\\").replace('"', '\\"')

    mcp_section = (
        "\n[mcp_servers.nexora]\n"
        'command = "python"\n'
        'args = ["/app/src/mcp_server.py"]\n'
        "\n[mcp_servers.nexora.env]\n"
        f'NX_CHAT_ID = "{_q(chat_id)}"\n'
        f'NX_AGENT_ID = "{_q(agent_id)}"\n'
        f'NX_AGENT_NAME = "{_q(agent_name)}"\n'
    )

    with open(config_path, "w") as f:
        f.writelines(filtered)
        f.write(mcp_section)


async def _stream_codex_cli(provider: Provider, messages: list[dict], **kw) -> AsyncIterator[str]:
    """Invoke the `codex` CLI as a subprocess for OAuth-authenticated accounts.

    Codex CLI outputs NDJSON events on stdout:
      {"type":"thread.started","thread_id":"..."}
      {"type":"turn.started"}
      {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
      {"type":"turn.completed","usage":{"input_tokens":N,"output_tokens":N,...}}

    Session isolation: each invocation gets its own HOME directory so that:
    - The MCP server entry is injected into config.toml without races between
      concurrent chats that share the same OAuth provider.
    - Codex starts in an empty workspace/ directory so bash exploration via
      `ls` / `find` / `cat` discovers nothing from the platform source tree.
    """
    import os
    import shutil
    import tempfile

    home_dir = provider.auth_path
    if not home_dir or not Path(home_dir).exists():
        raise ProviderError("Codex OAuth: auth directory not found — re-authenticate in Settings")

    _user_id = str(kw.get("user_id") or "")
    _org_id = str(kw.get("org_id") or "")
    if _user_id or _org_id:
        _allowed, _reason = await check_cli_rate_limit(_user_id, _org_id)
        if not _allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=429, detail=_reason)

    system_ctx, user_prompt = _build_cli_prompt(messages, kw.get("system_prompt"))
    full_prompt = f"{system_ctx}\n\n{user_prompt}".strip() if system_ctx else user_prompt

    chat_id    = kw.get("chat_id") or ""
    agent_id   = kw.get("agent_id") or ""
    agent_name = kw.get("agent_name") or ""
    model      = kw.get("model_override") or provider.model_name or _get_default_model("codex")

    session_home = tempfile.mkdtemp(prefix="ac_session_", dir=home_dir)
    try:
        src_codex = os.path.join(home_dir, ".codex")
        dst_codex = os.path.join(session_home, ".codex")
        os.makedirs(dst_codex, exist_ok=True)
        for fname in ("auth.json", "installation_id"):
            src_f = os.path.join(src_codex, fname)
            if os.path.isfile(src_f):
                shutil.copy2(src_f, os.path.join(dst_codex, fname))

        _write_codex_mcp_config(
            os.path.join(dst_codex, "config.toml"),
            chat_id, agent_id, agent_name,
        )

        work_dir = os.path.join(session_home, "workspace")
        os.makedirs(work_dir)

        cmd = [
            _get_cli_command("codex"), "exec",
            "--skip-git-repo-check",
            "--json",
            "--ephemeral",
            "-C", work_dir,
            "--model", model,
        ]
        if get_settings().allow_cli_bypass_permissions:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        cmd.append(full_prompt)

        env = {
            **_cli_env(session_home),
            "CODEX_HOME": dst_codex,
        }
        meta: dict = {"provider": "codex", "model": model}

        # Surface Codex multi-agent sub-agents (from collab_tool_call stream items)
        # as live Nexora sub-chats. Only active when bound to a real chat.
        from src.providers.cli_observability.codex_subagents import CodexSubagentTracker
        _sub_ctx = {
            "chat_id": chat_id, "agent_id": agent_id,
            "agent_name": agent_name, "org_id": kw.get("org_id"),
        }
        sub_tracker = CodexSubagentTracker(_sub_ctx, model, provider.name) if chat_id else None

        logger.info(f"Codex CLI: CODEX_HOME={dst_codex} model={model} chat={chat_id}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=work_dir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        yielded = False
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                evt = data.get("type", "")

                if evt == "thread.started":
                    meta["thread_id"] = data.get("thread_id")

                elif evt == "item.completed":
                    item = data.get("item", {})
                    if item.get("type") == "agent_message":
                        text = item.get("text", "")
                        if text:
                            yielded = True
                            yield text
                    elif sub_tracker and item.get("type") == "collab_tool_call":
                        await sub_tracker.handle_item(item)

                elif evt == "turn.completed":
                    usage = data.get("usage", {})
                    if usage:
                        meta["usage"] = usage

            except json.JSONDecodeError:
                pass

        if sub_tracker:
            await sub_tracker.close_all()

        await proc.wait()
        if proc.returncode != 0 and not yielded:
            stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
            if stderr_text:
                raise ProviderError(f"Codex CLI error: {stderr_text[:300]}")

    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"Codex CLI subprocess error: {e}")
    finally:
        shutil.rmtree(session_home, ignore_errors=True)

    yield _metadata_event(meta)
