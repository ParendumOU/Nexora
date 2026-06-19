# Nexora CLI

The Nexora CLI (`nexora`) lets you run and manage the Nexora AI agent platform entirely from your terminal — no browser required. It talks directly to the backend API and supports two operating modes:

| Mode | What runs | Use case |
|------|-----------|----------|
| **Docker** (default) | Full stack via `make dev` / `make up` | Full web UI + CLI |
| **Native** | Backend as an OS service, data stores via Docker or local | CLI-only, lighter footprint |

---

## Installation

### Prerequisites

- Python 3.11 or newer
- pip

### Install

```bash
# From the repo root
pip install -e ./cli

# Verify
nexora --version
```

> **Windows note:** The `nexora` binary lands in `%APPDATA%\Python\Python3xx\Scripts\`. If that is not in your `PATH`, either add it or invoke as `python -m nexora_cli.main`.

### PATH fix (Windows)

```powershell
# Add to current session
$env:PATH += ";$env:APPDATA\Python\Python313\Scripts"

# Add permanently (user profile)
[Environment]::SetEnvironmentVariable(
  "PATH",
  "$env:PATH;$env:APPDATA\Python\Python313\Scripts",
  "User"
)
```

---

## Quick start

### Option A — against a running Docker stack

```bash
# Start the stack first
make dev          # or: make up

# Auto-detects the backend (tries :8000, :8080, :80)
nexora setup      # interactive wizard — creates account + adds provider + agent
nexora chat       # open interactive REPL
```

### Option B — native backend (no full Docker)

```bash
# 1. Start only PostgreSQL + Redis
docker compose -f docker-compose.data.yml up -d

# 2. Copy and fill environment
cp .env.example .env

# 3. Run the setup wizard — picks "Native" mode
nexora setup

# 4. Install backend as OS service (auto-start on boot)
nexora service install

# 5. Start it
nexora service start

# 6. Chat
nexora chat
```

---

## Authentication

```
nexora auth login [--email EMAIL] [--password PASSWORD]
nexora auth logout
nexora auth register [--email EMAIL] [--password PASSWORD] [--name NAME] [--org ORG]
nexora auth whoami
nexora auth switch-org ORG_ID
```

Tokens are stored in `~/.nexora/config.json` and refreshed automatically. On expiry the CLI prompts for re-login.

---

## Service management (`nexora service`)

Manages the FastAPI backend as a native OS service — not needed when using Docker mode.

| Platform | Mechanism | Unit file location |
|----------|-----------|-------------------|
| macOS | launchd | `~/Library/LaunchAgents/ai.nexora.backend.plist` |
| Linux | systemd --user | `~/.config/systemd/user/nexora-backend.service` |
| Windows | schtasks | Task Scheduler — `NexoraBackend` |

```
nexora service install    # register with OS service manager (auto-start on boot)
nexora service uninstall  # remove from OS service manager
nexora service start      # start backend now
nexora service stop       # stop backend
nexora service restart    # restart backend
nexora service status     # show running/stopped, PID, uptime
nexora service logs       # tail logs
nexora service logs --follow --lines 200
```

### What `install` does

`nexora service install` requires:

- `--python PATH` — path to the Python executable (default: auto-detected)
- `--backend-dir PATH` — path to `backend/` (default: auto-detected relative to config)
- `--env-file PATH` — path to `.env` (default: auto-detected)

The service reads `DATABASE_URL` and `REDIS_URL` from the env file. If you chose managed data stores during setup, those point to `docker-compose.data.yml` containers.

---

## Setup wizard (`nexora setup`)

Five-step interactive wizard:

```
Step 1/5: Service mode
  Native or Docker

Step 2/5: Data stores  (native only)
  Managed (docker-compose.data.yml) or Manual (supply DATABASE_URL / REDIS_URL)

Step 3/5: Account
  Log in or register

Step 4/5: First AI provider
  OpenAI / Anthropic / Ollama / Skip

Step 5/5: First agent
  Name + system prompt
```

Re-run any time: `nexora setup` (safe to run again, skips already-done steps).

---

## Provider management (`nexora providers`)

```
nexora providers list
nexora providers add                          # interactive
nexora providers add --name "My OpenAI" --type openai --key sk-...
nexora providers add --type ollama --url http://localhost:11434
nexora providers remove PROVIDER_ID
nexora providers test PROVIDER_ID
nexora providers chains list
nexora providers chains add                   # interactive fallback chain builder
nexora providers chains remove CHAIN_ID
```

### Supported provider types

| Key | Auth | Notes |
|-----|------|-------|
| `openai` | API key | GPT-4o, o4-mini, etc. |
| `anthropic` | API key | Claude 3.x / 4.x |
| `ollama` | None | Local — requires running Ollama server |
| `google` | OAuth | Gemini models |
| `mistral` | API key | |
| `deepseek` | API key | |
| `groq` | API key | |
| `openrouter` | API key | Multi-provider routing |
| `lmstudio` | None | Local — OpenAI-compat endpoint |

---

## Model profiles (`nexora models`)

Named model configurations that can be assigned to agents and chats.

```
nexora models list                    # show models per provider
nexora models profiles list
nexora models profiles add            # interactive
nexora models profiles remove PROFILE_ID
```

---

## Agent management (`nexora agents`)

```
nexora agents list
nexora agents create                  # interactive
nexora agents create --name "Dev Bot" --prompt system_prompt.md
nexora agents update AGENT_ID --name "New Name" --temperature 0.7
nexora agents show AGENT_ID
nexora agents delete AGENT_ID

# Memory
nexora agents memory list AGENT_ID
nexora agents memory add AGENT_ID --content "Always reply in Spanish" --type instruction
nexora agents memory add AGENT_ID --content "User prefers concise answers" --type fact
nexora agents memory remove AGENT_ID MEMORY_ID
```

Memory types: `fact` | `instruction` | `context` | `rule`

---

## Chat (`nexora chat`)

```
nexora chat                           # open REPL (last active chat or creates new)
nexora chat new                       # create new chat, open REPL
nexora chat new --agent AGENT_ID --title "Sprint planning"
nexora chat list
nexora chat open CHAT_ID
nexora chat history [CHAT_ID] --limit 20
```

### Interactive REPL

The REPL streams responses in real-time over WebSocket.

```
[AgentName] > Hello! What can you do?

AgentName: I can help you with...

[AgentName] > /help
```

**REPL commands:**

| Command | Action |
|---------|--------|
| `/exit` | Close the REPL |
| `/new` | Start a new chat |
| `/switch AGENT_ID` | Change active agent |
| `/history` | Show last 10 messages |
| `/clear` | Clear the screen |
| `/agents` | List available agents |

---

## Workflows (`nexora workflows`)

```
nexora workflows list
nexora workflows create               # interactive
nexora workflows activate WF_ID
nexora workflows deactivate WF_ID
nexora workflows trigger WF_ID
nexora workflows trigger WF_ID --payload '{"key":"value"}'
nexora workflows runs WF_ID
nexora workflows delete WF_ID
```

### Trigger types

| Type | Config |
|------|--------|
| `cron` | `cron_expr` (e.g. `"0 9 * * 1"`) + `prompt` |
| `webhook` | Auto-generated URL — POST to trigger |
| `telegram` | Linked to a Telegram integration |
| `github` | GitHub event webhook |

---

## Schedules (`nexora schedules`)

```
nexora schedules list
nexora schedules create               # interactive (name, agent, cron/interval, prompt)
nexora schedules activate SCHED_ID
nexora schedules deactivate SCHED_ID
nexora schedules trigger SCHED_ID     # run immediately
nexora schedules delete SCHED_ID
```

---

## Integrations (`nexora integrations`)

```
nexora integrations list
nexora integrations add               # interactive — select type, enter config
nexora integrations remove INT_ID

# Telegram-specific
nexora integrations telegram setup    # guided Telegram bot setup
nexora integrations telegram pending  # list users awaiting approval
nexora integrations telegram approve  # approve a pending user
```

### Telegram setup walkthrough

```
nexora integrations telegram setup

Bot token: <paste token from @BotFather>
Integration name: My Telegram Bot
Linked agent: [select from list]

✓ Integration created
  Webhook: https://your-domain.com/api/integrations/webhook/...
  Users who message your bot will appear in: nexora integrations telegram pending
```

---

## Tasks (`nexora tasks`)

```
nexora tasks list
nexora tasks list --status in_progress
nexora tasks create --title "Fix login bug" --agent AGENT_ID
nexora tasks update TASK_ID --status completed
nexora tasks show TASK_ID
```

Status values: `pending` | `in_progress` | `completed` | `failed`

---

## Issues (`nexora issues`)

```
nexora issues list
nexora issues list --status open --project PROJECT_ID
nexora issues create --title "Auth fails on mobile" --priority high --project PROJECT_ID
nexora issues update ISSUE_ID --status closed
nexora issues show ISSUE_ID
```

Priority values: `low` | `medium` | `high` | `urgent`

---

## Seeds (`nexora seeds`)

Seeds are the file-based definitions for agents, tools, skills, and personas.

```
nexora seeds catalog                  # list all available seeds
nexora seeds export --types agent,tool --output my-seeds.zip
nexora seeds import my-seeds.zip
```

---

## Usage statistics (`nexora usage`)

```
nexora usage                          # summary: tokens + tool calls (last 30 days)
nexora usage models                   # breakdown by model
nexora usage agents                   # breakdown by agent
```

---

## Health check (`nexora doctor`)

```
nexora doctor
```

Runs 5–7 checks and prints a pass/fail table with fix hints:

| Check | What it verifies |
|-------|-----------------|
| Backend reachable | `GET /health` responds |
| Auth token valid | `GET /api/users/me` succeeds |
| Active organization | Org record exists |
| AI provider configured | At least one active provider |
| Agent exists | At least one agent |
| Native service installed | Service is running (native mode only) |
| Database reachable | asyncpg connects (native + manual data mode only) |

---

## JSON output

Every list command accepts `--json` for machine-readable output:

```bash
nexora agents list --json
nexora providers list --json | jq '.[].name'
nexora chat list --json
```

---

## Configuration file

Stored at `~/.nexora/config.json` (cross-platform via `platformdirs`):

```json
{
  "api_url": "http://localhost",
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "active_org_id": "uuid",
  "active_agent_id": "uuid",
  "active_chat_id": "uuid",
  "service_mode": "docker",
  "data_mode": "docker",
  "database_url": null,
  "redis_url": null,
  "backend_log_file": null
}
```

**Config file locations:**

| Platform | Path |
|----------|------|
| Windows | `%LOCALAPPDATA%\nexora\nexora\config.json` |
| macOS | `~/Library/Application Support/nexora/config.json` |
| Linux | `~/.config/nexora/config.json` |

### Override API URL

```bash
# Edit config directly
python -c "
from nexora_cli.config import get_config, save_config
cfg = get_config()
cfg.api_url = 'https://nexora.mycompany.com'
save_config(cfg)
"
```

---

## Troubleshooting

### "Backend reachable — FAIL"

The CLI could not reach the API. Checks in order:

1. Is the Docker stack running? `docker compose ps`
2. Is the native service running? `nexora service status`
3. Is the API URL correct? `cat ~/.nexora/config.json | grep api_url`
4. Try: `curl http://localhost/health`

Auto-detection on first run tries `:8000` (native) → `:8080` (docker-dev) → `:80` (docker-prod). If your setup uses a different port, update `api_url` manually.

### "Auth token valid — FAIL"

```bash
nexora auth login
```

### "Expecting value: line 1 column 1"

JSON parse error — usually a 307 redirect not followed. Upgrade to the latest CLI version (fixed in `fix(cli)` commit).

### WebSocket stream hangs

Check backend logs:

```bash
nexora service logs --follow      # native mode
docker compose logs -f backend    # docker mode
```

### Windows: `nexora` not found

```powershell
# Find where it was installed
Get-ChildItem "$env:APPDATA\Python" -Recurse -Filter "nexora.exe" 2>$null
# Add that Scripts directory to PATH
```

### Linux / macOS systemd unit not loading

```bash
systemctl --user daemon-reload
systemctl --user status nexora-backend
journalctl --user -u nexora-backend -n 50
```

---

## Data-only Docker stack

`docker-compose.data.yml` at the project root starts only PostgreSQL 16 and Redis 7 — useful when running the backend natively but wanting managed data stores:

```bash
docker compose -f docker-compose.data.yml up -d

# Default credentials (override via env vars):
# PostgreSQL: nexora / nexora_local @ localhost:5432
# Redis:      password nexora_local @ localhost:6379
```

Override defaults:

```bash
POSTGRES_PASSWORD=secret REDIS_PASSWORD=secret \
  docker compose -f docker-compose.data.yml up -d
```

---

## Uninstall

```bash
# Remove the package
pip uninstall nexora

# Remove config and logs
# Windows:  rmdir /s %LOCALAPPDATA%\nexora
# macOS/Linux: rm -rf ~/.config/nexora

# Remove OS service (if installed)
nexora service uninstall
```
