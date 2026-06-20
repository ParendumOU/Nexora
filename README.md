<div align="center">

<img src=".github/logo.png" alt="Nexora" width="110">

# Nexora

**Multi-tenant AI-agent orchestration platform.**
Define agents with personas, skills, and tools. Let them chat in real time, execute tools,
decompose work, delegate to sub-agents, and stream results — all self-hosted, on your own infra.

![License](https://img.shields.io/github/license/ParendumOU/Nexora)
![Release](https://img.shields.io/github/v/release/ParendumOU/Nexora?sort=semver)
![Stars](https://img.shields.io/github/stars/ParendumOU/Nexora?style=social)

**[🌐 Website](https://nexora.parendum.com) · [📖 Docs](https://docs.nexora.parendum.com) · [🧩 Marketplace](https://marketplace.nexora.parendum.com)**

<br>

<a href="https://nexora.parendum.com">
  <img src="https://github.com/ParendumOU/Nexora/releases/download/v1.1.3/nexora_demo.gif" alt="Nexora demo" width="720">
</a>

▶ **[Watch the full demo at nexora.parendum.com](https://nexora.parendum.com)**

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

## Screenshots

| Chat | Orchestration (sub-agents + task tree) |
|------|----------------------------------------|
| <img src=".github/chat-interface.png" alt="Nexora chat" width="420"> | <img src=".github/pm-08-panel-task-tree.png" alt="Nexora orchestration" width="420"> |

More in the [documentation](https://docs.nexora.parendum.com).

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

<a href="https://www.star-history.com/?repos=ParendumOU%2FNexora&type=date&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=ParendumOU/Nexora&type=date&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=ParendumOU/Nexora&type=date&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=ParendumOU/Nexora&type=date&legend=top-left" />
  </picture>
</a>
