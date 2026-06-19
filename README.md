<div align="center">

# Nexora

**Multi-tenant AI-agent orchestration platform.**
Define agents with personas, skills, and tools. Let them chat in real time, execute tools,
decompose work, delegate to sub-agents, and stream results — all self-hosted, on your own infra.

![License](https://img.shields.io/github/license/ParendumOU/Nexora)
![Release](https://img.shields.io/github/v/release/ParendumOU/Nexora?sort=semver)
![Stars](https://img.shields.io/github/stars/ParendumOU/Nexora?style=social)

</div>

---

## What is Nexora?

Nexora is the **free, MIT-licensed OSS core** of an AI-agent orchestration platform. Users
build agents (personas + skills + tools), and those agents collaborate in real time:
they run tools, break work into tasks, spawn bounded sub-agents, and stream their output
over WebSocket or SSE.

This repository is **pure platform** — zero billing, licensing, or paywall logic. The paid
self-hosted product (NexoraCloud) consumes this repo and layers commercial features on top.

### Highlights

- **Agent builder** — visual React-Flow graph: personas, skills, tools, sub-agents, bounded delegation.
- **~46 LLM providers** (+3 OAuth) — Claude, Gemini, OpenAI, Ollama, Vertex, Bedrock, Azure,
  Cohere, DeepSeek, Groq, Mistral, xAI, Perplexity, Together, Fireworks, OpenRouter, and more.
- **~90 built-in tools / ~15 skills** — Slack, Discord, Jira, Linear, Notion, PagerDuty, Google
  Drive, S3, Kubernetes, Playwright, hardened `http_request` (SSRF allowlist), agent-to-agent messaging.
- **Knowledge base / RAG** (pgvector) + **semantic memory** search + **multimodal image input**.
- **Real-time streaming** over WebSocket, with an SSE alternative.
- **Multi-tenant auth** — email/password (Argon2), JWT, API keys, invite-only mode, TOTP 2FA.
- **Marketplace client** — install community skills/tools/personas/agents with dependency auto-install.
- **Recovery engine** — retries, circuit breaker, stale-heartbeat watchdog.
- **Full-platform backup / restore** — export a whole instance (or one org) to a portable ZIP.
- **Clients** — web UI, [terminal client (NexoraCLI)](https://github.com/ParendumOU/Nexora-CLI),
  and a [mobile app (NexoraMobile)](https://github.com/ParendumOU/Nexora-Mobile).

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic |
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind, Zustand, React Flow |
| Data | PostgreSQL 16 + pgvector, Redis 7 |
| Proxy | nginx 1.27 |
| Runtime | Docker Compose |

---

## Quick start

```bash
git clone https://github.com/ParendumOU/Nexora.git
cd Nexora

cp .env.example .env          # then set SECRET_KEY + ENCRYPTION_KEY (see SETUP.md)

make dev                      # dev stack: backend :8000, frontend :3000, nginx :8080
# or
make up                       # production stack (nginx on HTTP_PORT, default 80)

docker compose exec backend alembic upgrade head   # run migrations on first boot
```

First visit with no users → `/setup` to create the admin account.
Full instructions in [`SETUP.md`](SETUP.md).

### Common commands

```bash
make dev      # dev (hot reload)
make up       # production
make down     # stop
make logs     # tail logs
make clean    # stop + wipe volumes (DESTRUCTIVE)
```

---

## Project layout

```
backend/        FastAPI app (agents, orchestration, providers, tools, RAG, auth)
frontend/       Next.js 15 web UI
cli/            Python (Typer) terminal client shipped with the core
nginx/          reverse proxy config
docker-compose*.yml   prod / dev / data-only stacks
SETUP.md        standalone setup guide
```

---

## Clients

| Client | Repo |
|--------|------|
| Terminal (Go TUI) | [ParendumOU/Nexora-CLI](https://github.com/ParendumOU/Nexora-CLI) |
| iOS / Android | [ParendumOU/Nexora-Mobile](https://github.com/ParendumOU/Nexora-Mobile) |

---

## License

[MIT](LICENSE) © Parendum OÜ

---

## Star history

<a href="https://star-history.com/#ParendumOU/Nexora&Date">
  <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=ParendumOU/Nexora&type=Date" width="640">
</a>
