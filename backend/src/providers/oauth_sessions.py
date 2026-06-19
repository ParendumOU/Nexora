"""Manages pexpect/subprocess-based CLI login sessions for provider OAuth flows."""
import os
import re
import time
import json
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


_sessions: dict[str, "LoginSession"] = {}
_lock = threading.Lock()

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_URL_RE = re.compile(r'https?://[^\s>]+')
_DEVICE_CODE_RE = re.compile(r'\b[A-Z0-9]{4}-[A-Z0-9]{4,8}\b')


def _get_auth_providers_dir() -> str:
    from src.core.config import get_settings
    return get_settings().auth_providers_dir


class LoginSession:
    def __init__(self, provider: str, account_name: str, home_dir: str):
        self.provider = provider
        self.account_name = account_name
        self.home_dir = home_dir
        self.pexpect_child = None
        self.process: Optional[subprocess.Popen] = None
        self.output: list[str] = []
        self.auth_url: Optional[str] = None
        self.device_code: Optional[str] = None
        self.status = "starting"
        self.start_time = datetime.now()
        self.error: Optional[str] = None


def _account_home(provider: str, account_name: str) -> str:
    return str(Path(_get_auth_providers_dir()) / provider / account_name)


def _read_json(path: Path) -> dict | None:
    try:
        if path.exists() and path.stat().st_size > 2:
            return json.loads(path.read_text())
    except Exception:
        pass
    return None


def _extract_token_pair(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else None
    source = nested or payload
    access_token = source.get("access_token", source.get("accessToken"))
    refresh_token = source.get("refresh_token", source.get("refreshToken"))
    id_token = source.get("id_token", source.get("idToken"))
    expires_at = source.get("expires_at", source.get("expiresAt"))
    if not any([access_token, refresh_token, id_token]):
        return None
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": expires_at,
    }


def _get_credential_candidates(provider_key: str, home: str | Path) -> list[Path]:
    """Load credential path patterns from the provider seed and resolve against home."""
    from src.seeds.loader import get_provider
    pdef = get_provider(provider_key)
    if not pdef:
        return []
    base = Path(home)
    return [base / rel for rel in pdef.get("credential_paths", [])]


def _creds_ready(provider_key: str, home: str | Path) -> bool:
    return any(
        p.exists() and p.stat().st_size > 10
        for p in _get_credential_candidates(provider_key, home)
    )


# ── Credential format readers ─────────────────────────────────────────────────
# Each reader receives the resolved list of candidate Paths for a provider.

def _read_creds_claude_oauth(paths: list[Path]) -> dict | None:
    if not paths:
        return None
    legacy = _read_json(paths[0])
    oauth = legacy.get("claudeAiOauth", {}) if isinstance(legacy, dict) else {}
    if isinstance(oauth, dict) and any(oauth.get(k) for k in ("accessToken", "refreshToken", "expiresAt")):
        return {
            "access_token": oauth.get("accessToken"),
            "refresh_token": oauth.get("refreshToken"),
            "expires_at": oauth.get("expiresAt"),
        }
    for candidate in paths[1:]:
        tokens = _extract_token_pair(_read_json(candidate))
        if tokens:
            return tokens
    return None


def _read_creds_raw_json(paths: list[Path]) -> dict | None:
    return _read_json(paths[0]) if paths else None


def _read_creds_token_pair(paths: list[Path]) -> dict | None:
    return _extract_token_pair(_read_json(paths[0])) if paths else None


_CRED_READERS = {
    "claude_oauth": _read_creds_claude_oauth,
    "raw_json":     _read_creds_raw_json,
    "token_pair":   _read_creds_token_pair,
}


def _collect(session: LoginSession, text: str):
    for raw in text.split("\n"):
        clean = _ANSI_RE.sub('', raw).strip()
        if clean and clean not in session.output:
            session.output.append(clean)
            url_m = _URL_RE.search(clean)
            if url_m and not session.auth_url:
                session.auth_url = url_m.group(0).rstrip(".,")
                session.status = "awaiting_auth"
            code_m = _DEVICE_CODE_RE.search(clean)
            if code_m and not session.device_code:
                session.device_code = code_m.group(0)


_OAUTH_RUNNERS = {
    "claude": lambda s: _run_claude(s),
    "gemini": lambda s: _run_gemini(s),
    "codex":  lambda s: _run_codex(s),
}


def start_login(provider: str, account_name: str) -> dict:
    """Start a CLI login session. Returns immediately; runs in background thread."""
    if provider not in _OAUTH_RUNNERS:
        raise ValueError(f"OAuth login not supported for provider: {provider}")

    key = f"{provider}_{account_name}"
    home_dir = _account_home(provider, account_name)
    Path(home_dir).mkdir(parents=True, exist_ok=True)

    session = LoginSession(provider, account_name, home_dir)

    with _lock:
        existing = _sessions.get(key)
        if existing:
            if existing.pexpect_child:
                try:
                    existing.pexpect_child.close(force=True)
                except Exception:
                    pass
            if existing.process:
                try:
                    existing.process.kill()
                except Exception:
                    pass
        _sessions[key] = session

    threading.Thread(target=_OAUTH_RUNNERS[provider], args=(session,), daemon=True).start()

    return {"session_key": key, "status": "started"}


def get_status(provider: str, account_name: str) -> dict:
    key = f"{provider}_{account_name}"
    with _lock:
        session = _sessions.get(key)
    if not session:
        return {"status": "not_found"}
    return {
        "status": session.status,
        "auth_url": session.auth_url,
        "device_code": session.device_code,
        "output": session.output[-20:],
        "error": session.error,
    }


def submit_code(provider: str, account_name: str, code: str) -> bool:
    key = f"{provider}_{account_name}"
    with _lock:
        session = _sessions.get(key)
    if not session:
        return False

    # Always strip whitespace — browsers may include trailing newlines/spaces
    code = code.strip()

    if session.pexpect_child:
        if not session.pexpect_child.isalive():
            # Process already exited — monitor thread will detect creds file
            session.output.append("[info] CLI already exited; checking credentials...")
            return True
        try:
            session.pexpect_child.send(code + "\r")
            session.output.append(f"[auto] Code submitted ({len(code)} chars)")
            return True
        except Exception:
            return False
    if session.process and session.process.stdin:
        try:
            session.process.stdin.write(code + "\n")
            session.process.stdin.flush()
            session.output.append("[auto] Code submitted")
            return True
        except Exception:
            return False
    return False


def read_provider_credentials(provider: str, home: str | Path) -> Optional[dict]:
    """Read stored credentials from the provider auth directory using the seed-defined format."""
    from src.seeds.loader import get_provider
    pdef = get_provider(provider)
    if not pdef:
        return None
    paths = _get_credential_candidates(provider, home)
    fmt = pdef.get("credential_format", "raw_json")
    reader = _CRED_READERS.get(fmt, _read_creds_raw_json)
    try:
        return reader(paths)
    except Exception:
        return None


def get_credentials(provider: str, account_name: str) -> Optional[dict]:
    return read_provider_credentials(provider, _account_home(provider, account_name))


# ── pexpect/subprocess workers ─────────────────────────────────────────────────

_SUCCESS_RE = re.compile(
    r'Login successful|Logged in as|You are now logged|Successfully logged|Successfully authenticated|Authentication complete',
    re.IGNORECASE,
)
_CODE_PROMPT_RE = re.compile(
    r'(enter|paste|type|provide|input).*code|authorization code\s*:',
    re.IGNORECASE,
)
_GEMINI_CODE_PROMPT_RE = re.compile(
    r'(enter|paste|type|provide|input).*(authorization|auth).*code|authorization code\s*:|authcode',
    re.IGNORECASE,
)


def _run_claude(s: LoginSession):
    # Wipe stale credentials before starting monitor
    for _stale in _get_credential_candidates("claude", s.home_dir):
        try:
            _stale.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Background monitor thread (mirrors external-orchestratorai approach) ──
    def _monitor():
        for _ in range(150):  # 5 min max
            if s.status in ("success", "finished", "timeout"):
                return
            if _creds_ready("claude", s.home_dir):
                s.status = "success"
                s.output.append("[auto] Authentication complete!")
                return
            time.sleep(2)

    threading.Thread(target=_monitor, daemon=True).start()

    try:
        import pexpect
        from src.seeds.loader import get_provider as _gp
        _claude_def = _gp("claude") or {}
        _cli_cmd = _claude_def.get("cli_command", "claude")
        _cli_args = _claude_def.get("cli_login_args", ["auth", "login", "--claudeai"])
        env = {
            **os.environ,
            "HOME": s.home_dir,
            "TERM": "xterm",
            "FORCE_COLOR": "0",
            "NO_COLOR": "1",
        }
        child = pexpect.spawn(
            _cli_cmd, _cli_args,
            encoding="utf-8", timeout=60, dimensions=(24, 1000), env=env,
        )
        s.pexpect_child = child

        try:
            child.expect(r'ctrl\+t.*disable\)', timeout=15)
            time.sleep(0.5)
            child.send('\r')
        except Exception:
            pass

        try:
            child.expect(r'Select.*method:', timeout=5)
            time.sleep(0.5)
            child.send('\r')
        except Exception:
            pass

        # Single continuous expect loop — same structure as external-orchestratorai
        while s.status not in ("success", "finished", "timeout"):
            try:
                idx = child.expect([
                    r'https?://',                        # 0 — auth URL
                    r'Login successful|Logged in as',    # 1 — success text
                    r'Press Enter to continue',          # 2 — press-enter prompt
                    r'Security notes',                   # 3 — appears after successful auth
                    _CODE_PROMPT_RE.pattern,             # 4 — code input prompt
                    r'(?i)(error|invalid|expired|failed|denied)',  # 5 — error text
                    pexpect.EOF,                         # 6
                    pexpect.TIMEOUT,                     # 7
                ], timeout=300)
            except Exception as e:
                s.output.append(f"[expect error] {e}")
                break

            before = str(child.before or "")
            after = str(child.after) if not isinstance(child.after, type) else ""
            _collect(s, before + after)

            if idx == 0:
                url_m = _URL_RE.search(before + after)
                if not url_m:
                    try:
                        child.expect(r'\r?\n|\r', timeout=5)
                        rest = _ANSI_RE.sub('', str(child.before or "")).strip()
                        url_m = _URL_RE.search(after + rest)
                        _collect(s, after + rest)
                    except Exception:
                        pass
                if url_m:
                    s.auth_url = url_m.group(0).rstrip(".,")
                    s.status = "awaiting_auth"
                    s.output.append(f"🔗 {s.auth_url}")

            elif idx == 1:
                s.output.append("[auto] Login detected! Sending Enter to finalize...")
                child.send('\r')
                # Don't set success here — let the monitor thread confirm via creds file

            elif idx == 2:
                child.send('\r')
                s.output.append("[auto] Dismissed 'Press Enter to continue'")

            elif idx == 3:
                # "Security notes" appears right after successful auth in the Claude CLI
                child.send('\r')
                s.status = "success"
                s.output.append("[auto] Authentication complete!")
                break

            elif idx == 4:
                if s.status != "awaiting_code":
                    s.status = "awaiting_code"
                    s.output.append("Paste the authorization code from the browser page")

            elif idx == 5:
                # Error message after code submission
                ctx = _ANSI_RE.sub('', (before + after)).strip()
                s.output.append(f"[error from CLI] {ctx[:200]}")
                s.error = ctx[:200]
                break

            elif idx in (6, 7):
                # EOF or timeout — monitor thread will catch creds file if written
                break

        child.close()
    except Exception as e:
        s.error = str(e)
        s.output.append(f"[error] {e}")

    if s.status not in ("success", "timeout"):
        s.status = "success" if _creds_ready("claude", s.home_dir) else "finished"


_GEMINI_TRUST_RE = re.compile(
    r'trust.*folder|don.t trust|\bTrust\b.*\(Gemini',
    re.IGNORECASE,
)


def _run_gemini(s: LoginSession):
    try:
        import pexpect
        gemini_dir = Path(s.home_dir) / ".gemini"
        gemini_dir.mkdir(parents=True, exist_ok=True)
        # Wipe stale credentials so the monitor thread doesn't fire a false
        # "success" from a previous login attempt with this account name.
        for _stale in _get_credential_candidates("gemini", s.home_dir):
            try:
                _stale.unlink(missing_ok=True)
            except Exception:
                pass
        (gemini_dir / "settings.json").write_text(
            json.dumps({
                "selectedAuthType": "oauth-personal",
                "useExternal": False,
                "theme": "Default",
                "autoUpdate": False,
                "security": {
                    "auth": {
                        "selectedType": "oauth-personal",
                    }
                },
            })
        )
        (gemini_dir / "projects.json").write_text('{"projects": {}}')

        def _monitor():
            for _ in range(150):  # 5 min max
                if s.status in ("success", "finished", "timeout"):
                    return
                if _creds_ready("gemini", s.home_dir):
                    s.status = "success"
                    s.output.append("[auto] Authentication complete!")
                    return
                time.sleep(2)

        threading.Thread(target=_monitor, daemon=True).start()

        from src.seeds.loader import get_provider as _gp
        _gemini_def = _gp("gemini") or {}
        _cli_cmd = _gemini_def.get("cli_command", "gemini")
        _cli_args = _gemini_def.get("cli_login_args", ["--yolo"])
        env = {
            **os.environ,
            "HOME": s.home_dir,
            "NO_BROWSER": "true",
            "TERM": "xterm",
            "FORCE_COLOR": "0",
            "NO_COLOR": "1",
        }
        child = pexpect.spawn(
            _cli_cmd, _cli_args,
            cwd=s.home_dir, encoding="utf-8", timeout=60, dimensions=(24, 1000), env=env,
        )
        s.pexpect_child = child

        # Handle pre-auth startup prompts (trust folder, theme picker, update banner).
        # Do NOT include https?:// here — consuming the URL without recording it would
        # cause the main loop to never see the auth link.
        for _ in range(10):
            try:
                idx2 = child.expect([
                    _GEMINI_TRUST_RE.pattern,                     # 0 — trust folder dialog
                    r'(?i)update available|updating now',          # 1 — update banner
                    r'(?i)(theme|press enter|continue|ctrl\+t)',   # 2 — misc startup prompts
                    pexpect.TIMEOUT,                               # 3 — nothing more to handle
                ], timeout=6)
                if idx2 == 0:
                    child.send('1\r')
                    s.output.append("[auto] Selected 'Trust folder'")
                    time.sleep(0.3)
                elif idx2 in (1, 2):
                    child.send('\r')
                    time.sleep(0.3)
                else:
                    break  # TIMEOUT — done with startup prompts
            except Exception:
                break

        while True:
            try:
                idx = child.expect([
                    r'https?://',                        # 0
                    _GEMINI_CODE_PROMPT_RE.pattern,      # 1
                    r'Authentication succeeded',          # 2
                    _GEMINI_TRUST_RE.pattern,            # 3 — trust dialog mid-flow
                    r'(?i)update available',             # 4 — update banner mid-flow
                    r'(?i)(error|failed)',               # 5
                    pexpect.EOF,                         # 6
                    pexpect.TIMEOUT,                     # 7
                ], timeout=300)
            except Exception as e:
                s.output.append(f"[expect error] {e}")
                break

            before = str(child.before or "")
            after = str(child.after) if not isinstance(child.after, type) else ""
            available = before + after
            _collect(s, available)

            if idx == 0:
                url_m = _URL_RE.search(available)
                if not url_m:
                    try:
                        child.expect(r'\r?\n|\r', timeout=5)
                        rest = _ANSI_RE.sub('', str(child.before or "")).strip()
                        url_m = _URL_RE.search(after + rest)
                        _collect(s, after + rest)
                    except Exception:
                        pass
                if url_m:
                    found_url = url_m.group(0).rstrip(".,")
                    # Prefer the Google OAuth consent URL over codeassist.google.com/authcode
                    if "codeassist.google.com/authcode" not in found_url:
                        s.auth_url = found_url
                    elif not s.auth_url:
                        s.auth_url = found_url
                    s.status = "awaiting_auth"
                    s.output.append("Open the link, authorize, then paste the code from https://codeassist.google.com/authcode")
            elif idx == 1:
                s.status = "awaiting_code"
                s.output.append("Paste the authorization code above")
            elif idx == 2:
                s.status = "success"
                break
            elif idx == 3:
                child.send('1\r')
                s.output.append("[auto] Selected 'Trust folder'")
                time.sleep(0.3)
            elif idx == 4:
                child.send('\r')
                time.sleep(0.3)
            elif idx in (5, 6, 7):
                if _creds_ready("gemini", s.home_dir):
                    s.status = "success"
                break
        child.close()
    except Exception as e:
        s.error = str(e)
        s.output.append(f"[error] {e}")

    if s.status not in ["success", "timeout"]:
        s.status = "success" if _creds_ready("gemini", s.home_dir) else "finished"


def _run_codex(s: LoginSession):
    """Codex device auth flow — subprocess stdout capture (no pexpect needed)."""
    # Wipe stale credentials before starting monitor
    for _stale in _get_credential_candidates("codex", s.home_dir):
        try:
            _stale.unlink(missing_ok=True)
        except Exception:
            pass
    try:
        def _monitor():
            for _ in range(150):  # 5 min max
                if s.status in ("success", "finished", "timeout"):
                    return
                if _creds_ready("codex", s.home_dir):
                    s.status = "success"
                    s.output.append("[auto] Authentication complete!")
                    return
                time.sleep(2)

        threading.Thread(target=_monitor, daemon=True).start()

        from src.seeds.loader import get_provider as _gp
        _codex_def = _gp("codex") or {}
        _cli_cmd = _codex_def.get("cli_command", "codex")
        _cli_args = _codex_def.get("cli_login_args", ["login", "--device-auth"])
        env = {
            **os.environ,
            "HOME": s.home_dir,
            "BROWSER": "none",
            "TERM": "xterm",
            "FORCE_COLOR": "0",
            "NO_COLOR": "1",
        }
        proc = subprocess.Popen(
            [_cli_cmd, *_cli_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        s.process = proc

        for line in iter(proc.stdout.readline, ''):
            clean = _ANSI_RE.sub('', line).strip()
            if not clean:
                continue
            s.output.append(clean)

            url_m = _URL_RE.search(clean)
            if url_m and not s.auth_url:
                s.auth_url = url_m.group(0).rstrip(".,")
                s.status = "awaiting_auth"

            code_m = _DEVICE_CODE_RE.search(clean)
            if code_m and not s.device_code:
                s.device_code = code_m.group(0)
                s.status = "awaiting_auth"

            if any(p in clean.lower() for p in ["successfully logged in", "login successful", "authenticated", "logged in"]):
                s.status = "success"

        proc.wait()

        # Check credentials file as fallback
        if _creds_ready("codex", s.home_dir):
            s.status = "success"

    except Exception as e:
        s.error = str(e)
        s.output.append(f"[error] {e}")

    if s.status not in ["success", "timeout"]:
        s.status = "success" if _creds_ready("codex", s.home_dir) else "finished"
