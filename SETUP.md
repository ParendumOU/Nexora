# Nexora — Setup Guide

Nexora is the open-source core. Run it standalone for development or self-hosting.

---

## Requirements

- Docker + Docker Compose
- Git

---

## One-command install

The installer asks a couple of questions, generates all secrets, writes `.env`,
starts the stack, and runs the migrations:

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/ParendumOU/Nexora/main/install.sh | bash
```

```powershell
# Windows (PowerShell)
powershell -c "irm https://raw.githubusercontent.com/ParendumOU/Nexora/main/install.ps1 | iex"
```

Prefer to do it by hand? Follow the steps below.

---

## Quick start

```bash
git clone https://github.com/ParendumOU/Nexora.git
cd nexora
cp .env.example .env
```

Edit `.env` — minimum required:

```env
POSTGRES_PASSWORD=strong-password-here
REDIS_PASSWORD=strong-password-here
SECRET_KEY=generate-with-python-secrets-token-urlsafe-64
ENCRYPTION_KEY=generate-with-fernet-generate-key
ENVIRONMENT=production
```

Generate values:
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"   # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
```

Start:
```bash
make up
```

Run migrations (first time only):
```bash
docker compose exec backend alembic upgrade head
```

Access: `http://localhost:80`

---

## Development (hot-reload)

```bash
make dev
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/api/docs`

---

## First login

On first visit the app detects no users exist and redirects to `/setup`.  
Create your admin account there.

---

## Optional integrations

Add to `.env` as needed:

```env
TELEGRAM_BOT_TOKEN=
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY=
GITLAB_APP_ID=
GITLAB_APP_SECRET=
SMTP_HOST=smtp.sendgrid.net
SMTP_USER=apikey
SMTP_PASSWORD=SG.xxxxx
APP_URL=https://your-domain.com
```

---

## Invite-only registration

To prevent open registration:

```env
REQUIRE_INVITE=true
```

First account can still be created via `/setup`. After that, all registrations need an invite link (generated from Settings → Team).

---

## Docker socket hardening

Agents spawn sandbox containers to do their work (the `shell_run` tool runs
`docker ...` / `docker compose up`, and the `docker_run`/`docker_build`/`docker_ps`/
`docker_logs` tools drive the docker CLI). The compose stack does **not** hand the
backend the raw host socket. Instead a filtering proxy sits in front of the daemon.

### Topology

```
backend ─┐
         ├─ tcp://docker-proxy:2375 ── docker-proxy ── /var/run/docker.sock (ro) ── dockerd
runner  ─┘        (internal network)   (allow/deny filter)
```

- `docker-proxy` ([`wollomatic/socket-proxy`](https://github.com/wollomatic/socket-proxy))
  is the **only** service that mounts `/var/run/docker.sock`, read-only.
- `backend` and `runner` set `DOCKER_HOST=tcp://docker-proxy:2375`. The docker CLI honors
  `DOCKER_HOST`, so every `docker`/`docker compose` call an agent makes is filtered
  transparently. No application code changed.
- The proxy listens on TCP `2375` on the internal compose network only: **no host port**,
  **not** behind nginx. It is locked down (`read_only`, `cap_drop: ALL`,
  `no-new-privileges`, 64 MB / 64-pid cap).

The goal: if an agent ever escapes its sandbox, it gets a locked-down subset of the
Docker API instead of host root. Policy lives in the `docker-proxy` `command:` block in
`docker-compose.yml`.

### Allow / deny policy

Everything is default-deny (HTTP 403 unless a method + path rule matches):

| Method | Allowed paths | Why |
|--------|---------------|-----|
| GET | `_ping`, `version`, `info`, `events*`, `containers*`, `images*`, `networks*`, `volumes*`, `exec*` | Version negotiation, inspect/list, logs, exec status. |
| HEAD | `_ping` | Daemon ping during negotiation. |
| POST | `containers/*`, `exec/*`, `images/*`, `build*`, `networks/*`, `volumes/*` | Create/run/exec containers, pull+build images, and the network/volume `create` that `docker compose up` needs. |
| DELETE | `containers/*`, `images/*`, `networks/*`, `volumes/*` | `--rm` cleanup and prune. |
| PUT | (none) | Not needed by any agent flow. |

Denied by omission: `/swarm`, `/nodes`, `/services`, `/tasks` (cluster takeover),
`/secrets`, `/configs` (credential theft), `/plugins` (host escape), `/commit`,
`/session`, `/grpc`, `/distribution`, `/system/df`, `/auth`.

`/info` is intentionally allowed: `docker compose up` calls it at startup and fails
without it. It is a low-severity host-metadata read, not an escape.

`DOCKER_BUILDKIT=0` is set on backend/runner so `docker build` uses the classic
`POST /build` endpoint; BuildKit's `/session`+`/grpc` stream is not exposed.

### Enforced vs. residual

**Enforced:** default-deny of the dangerous control plane, plus a **bind-mount source
allowlist** (`-allowbindmountfrom=/workspaces`) that parses the container-create body so
a container may only bind-mount host paths under `/workspaces`. `docker run -v /:/host`,
mounting the docker socket back in, `-v /etc:/etc`, etc. are refused. Named/anonymous
volumes are unaffected, so compose volumes keep working.

**Residual (NOT yet filtered):** `wollomatic/socket-proxy` inspects the request body
only for bind-mount sources. It does **not** reject other `HostConfig` escapes, so a
container created through the proxy can still request `Privileged: true`,
`PidMode/NetworkMode/IpcMode: host`, `CapAdd`, `Devices`, or
`SecurityOpt: seccomp=unconfined`. Closing this needs one of: a body-filtering proxy
that rejects those fields, a sandboxed runtime for agent workloads (gVisor / Kata /
sysbox), or a dedicated disposable Docker daemon (rootless DinD) for agent spawns.
Until then, rely on the agent-side guards (tool permission gates, the `shell_run` host
guard, `DENY_EXEC_TOOLS`) as compensating controls.

### Validating the policy

Point a docker CLI at the proxy and confirm allowed ops work and denied ops 403:

```bash
docker ps                                 # allowed
docker pull alpine                        # allowed
docker run --rm alpine true               # allowed
docker swarm init                         # denied (path not allowed)
docker secret ls                          # denied (path not allowed)
docker run --rm -v /:/host alpine true    # denied (bind mount restriction)
```

> **NexoraCloud:** Cloud has its own `docker-compose.yml` running this same core image;
> the identical `docker-proxy` service + `DOCKER_HOST` change must be mirrored there or
> Cloud keeps the raw socket. That change lives in the NexoraCloud repo.

---

## Useful make targets

```bash
make up          # start production
make dev         # start with hot-reload
make down        # stop
make logs        # tail logs
make clean       # stop + remove volumes (DESTRUCTIVE)
docker compose exec backend alembic revision --autogenerate -m "description"  # new migration
```
