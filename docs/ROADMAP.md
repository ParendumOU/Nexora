# Nexora — Roadmap

## Phase 1 — MVP ✅

### Infrastructure
- [x] Docker Compose: nginx, postgres, redis, backend, frontend
- [x] PostgreSQL schema with Alembic migrations
- [x] Redis for sessions, caching, rate-limit state, task queue

### Auth & Multi-tenancy
- [x] Email/password registration + JWT auth
- [x] Organizations with member roles
- [x] Per-org provider credentials (encrypted at rest)
- [x] Invitation-only registration (`REQUIRE_INVITE` flag, invite tokens)
- [x] Rate limiting on auth endpoints

### Provider System
- [x] Claude OAuth token provider
- [x] Gemini OAuth token provider
- [x] OpenAI API key provider
- [x] Ollama local provider
- [x] Provider chains with auto-fallback on rate limit
- [x] Provider health dashboard

### Chat Interface
- [x] Real-time streaming messages via WebSocket
- [x] Code blocks with syntax highlighting + copy
- [x] Model selector per chat
- [x] Chat history

### Agent Builder
- [x] Visual React Flow node editor
- [x] Built-in agent types (PM, Developer, QA, Researcher)
- [x] Soul editor (personality, expertise, system prompt)
- [x] Skills assignment per agent

### Projects
- [x] Create project with optional repo URL
- [x] Automatic PM agent instantiation
- [x] Task delegation to sub-agents
- [x] Project chat thread

### Integrations
- [x] GitHub: OAuth app, read repos, read issues/PRs
- [x] GitLab: OAuth2, read repos, read issues/MRs
- [x] Telegram: Bot webhook, route to agent
- [x] MCP (Model Context Protocol) server support

---

## Phase 2 — Enhanced Agents 🚧

- [ ] TOTP 2FA (Google Authenticator)
- [ ] Agent marketplace — browse + install community agents (frontend mock only; backend pending)
- [ ] Skills marketplace — browse + install community skills (frontend mock only; backend pending)
- [ ] Parallel sub-agent execution with progress tracking
- [ ] Agent execution logs + replay
- [ ] Docker sandbox resource limits (CPU, memory, time)
- [ ] GitHub: PR creation, code review comments
- [ ] GitLab: MR creation, code review comments
- [ ] Full-text / semantic search on messages (pgvector)
- [ ] WebSocket reconnection with exponential backoff
- [ ] Message deduplication (idempotency keys)
- [ ] Kubernetes sandbox provider

---

## Phase 3 — SaaS Features 🚧

> Implemented in **NexoraCloud** (private layer on top of core).

- [x] Stripe billing (Free, Starter, Pro, Team, Enterprise plans) — NexoraCloud
- [x] Usage tracking (LLM calls, agent runs, workflow runs per org) — NexoraCloud
- [x] Enterprise audit logs — NexoraCloud
- [ ] SSO (SAML 2.0 / OIDC) — architecture defined, not built
- [ ] Email notifications (payment failure, trial ending, password reset)
- [ ] Marketplace backend (package storage, Stripe Connect payouts)
- [ ] Fine-tuned models (bring your own fine-tune)
- [ ] Analytics dashboard (agent performance, cost tracking)
- [ ] API access for external integrations

---

## Phase 4 — Enterprise

- [ ] Multi-region deployment
- [ ] Private model hosting (vLLM integration)
- [ ] Custom skill development SDK
- [ ] Role-based skill access control
- [ ] Enterprise SSO with group sync
- [ ] SLA guarantees + priority support
- [ ] White-label option

---

## Tech Debt

- [ ] Docker sandbox CPU/memory/time resource limits on sub-agent containers
- [ ] Provider OAuth token refresh cycle (detect + surface expiry)
- [ ] Org member invite enforces plan user limits
- [ ] Trial expiry cron wired to APScheduler
- [ ] File upload to chat (images, PDFs for context)
- [ ] Agent output streaming to project workspace files
