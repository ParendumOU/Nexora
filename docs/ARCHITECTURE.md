# AgenticChats — System Architecture

## Overview

AgenticChats is a professional SaaS platform for AI-powered development teams. It combines:
- **DeerFlow-inspired UI**: Clean, dark, collapsible sidebar chat interface
- **OpenClaw-inspired agents**: Visual agent builder with skills marketplace
- **Paperclip-inspired projects**: PM agent that orchestrates specialized sub-agents
- **OAuth-first providers**: No API keys required — uses subscription OAuth tokens with auto-fallback

---

## Service Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           NGINX (port 80/443)                    │
│                     Reverse proxy + SSL termination              │
└───────────┬─────────────────────────┬───────────────────────────┘
            │                         │
     /api/* → :8000            /* → :3000
            │                         │
┌───────────▼──────────┐   ┌──────────▼──────────┐
│   FastAPI Backend     │   │   Next.js Frontend   │
│   (Python 3.12)       │   │   (React 19 / TS)    │
│   port 8000           │   │   port 3000          │
│                       │   │                      │
│   • REST API          │   │   • Chat UI          │
│   • WebSocket         │   │   • Agent Builder    │
│   • Agent Engine      │   │   • Project Board    │
│   • LangGraph         │   │   • Settings         │
└───────┬───────────────┘   └──────────────────────┘
        │
   ┌────┴──────────────────────────────────────┐
   │                                           │
┌──▼──────────┐  ┌──────────────┐  ┌──────────▼──────┐
│ PostgreSQL   │  │    Redis     │  │  Provider Pool  │
│ (data store) │  │(queue/cache) │  │  (OAuth tokens) │
└─────────────┘  └──────────────┘  └─────────────────┘
```

---

## Domain Model

### Users & Auth
- Users register / login via email+password (JWT sessions)
- Per-user **Provider Credentials**: OAuth tokens or API keys per LLM provider
- **Organizations**: team workspaces with member roles (owner, admin, member, viewer)

### Providers (LLM)
- Each provider: `name`, `type` (claude/gemini/openai/ollama/custom), `auth_type` (oauth/apikey)
- Rate limit tracking: last 429, cooldown expiry, request count
- **Fallback chain**: ordered list of providers; auto-switch on rate limit or failure
- Providers scoped per Organization (shared credentials for team) or per User

### Projects
- A Project has a name, description, repo (optional GitHub/GitLab URL), and assigned Provider chain
- Creating a Project instantiates a **Project Manager** agent
- PM analyzes incoming tasks → creates sub-agents (Developer, QA, Researcher, etc.) as needed
- Sub-agents have Docker sandbox execution for code

### Agents
- An Agent has: name, description, type, soul (system prompt), skills list, model preference
- **Agent Types**: project_manager, developer, qa_engineer, researcher, designer, devops, custom
- Agents are visually configured in the Agent Builder (React Flow node editor)
- Skills are assignable capabilities (bash, web_search, github_read, gitlab_write, etc.)

### Chats / Threads
- A Chat belongs to a User + (optionally) a Project
- Messages stream via WebSocket
- Supports: text, code blocks, artifacts (files), inline images
- Message roles: user, assistant, system, tool_result

### Integrations
- **Telegram**: Bot webhook → route to assigned agent/project
- **GitHub**: OAuth app, webhooks for PR/issue events, repo R/W via access token
- **GitLab**: OAuth2 app, webhooks for MR/issue events, repo R/W via access token

---

## Provider Fallback System

```
Request → ProviderRouter
  └─ Try primary provider
       ├─ Success → stream response
       └─ RateLimitError (429) or NetworkError
            └─ Mark provider cooling (TTL: 60s default)
                 └─ Try next provider in fallback chain
                      └─ No providers available → queue with retry
```

### Auth Types
| Provider   | Auth Method                                       |
|-----------|--------------------------------------------------|
| Claude     | OAuth token from claude.ai session cookie / CLI  |
| Gemini     | Google OAuth2 token from google.com session      |
| OpenAI     | API key or OAuth (Plus subscribers)              |
| Ollama     | No auth (local URL)                              |
| Custom     | Bearer token / API key                           |

---

## Agent Execution

### Project Workflow
```
User creates Project → PM Agent spawned
User sends task → PM Agent receives it
PM decomposes → creates sub-agent threads
  ├─ Developer Agent: code implementation in Docker sandbox
  ├─ QA Agent: test execution and review
  └─ Researcher Agent: web research, doc reading
PM aggregates results → responds to User
```

### Docker Sandboxes
- Each agent execution gets an isolated Docker container
- Shared volume: `/workspace` for project files
- Languages: Python, Node.js, bash, git
- Internet: enabled (for package installs, web requests)

---

## Frontend Architecture

```
src/
├── app/                          # Next.js App Router
│   ├── (auth)/                   # Login, register, onboarding
│   ├── (workspace)/              # Main app shell
│   │   ├── layout.tsx            # Sidebar + header layout
│   │   ├── page.tsx              # Dashboard / home
│   │   ├── chat/[id]/            # Chat thread view
│   │   ├── projects/             # Project list + detail
│   │   ├── agents/               # Agent builder
│   │   ├── integrations/         # Telegram, GitHub, GitLab
│   │   └── settings/             # Org settings, providers
│   └── api/                      # Next.js API routes (proxy)
├── components/
│   ├── layout/                   # Sidebar, header, shell
│   ├── chat/                     # Message, input, streaming
│   ├── agents/                   # Agent node editor
│   ├── projects/                 # Project board
│   └── ui/                       # Base design system (shadcn)
├── lib/
│   ├── api.ts                    # Backend API client
│   ├── ws.ts                     # WebSocket client
│   └── providers.ts              # React Query + providers
└── store/                        # Zustand state slices
```

---

## Backend Architecture

```
src/
├── api/
│   └── routers/                  # FastAPI routers
│       ├── auth.py               # Login, register, refresh
│       ├── users.py              # Profile, settings
│       ├── orgs.py               # Organizations, members
│       ├── projects.py           # Projects CRUD
│       ├── agents.py             # Agent CRUD + builder
│       ├── chats.py              # Threads + messages
│       ├── providers.py          # LLM provider config
│       ├── integrations.py       # Telegram, GitHub, GitLab
│       └── ws.py                 # WebSocket endpoint
├── agents/
│   ├── engine.py                 # LangGraph runner
│   ├── pm_agent.py               # Project Manager
│   ├── dev_agent.py              # Developer
│   ├── qa_agent.py               # QA Engineer
│   ├── research_agent.py         # Researcher
│   └── skills/                   # Tool definitions
├── providers/
│   ├── router.py                 # ProviderRouter (fallback logic)
│   ├── claude.py                 # Anthropic provider
│   ├── gemini.py                 # Google provider
│   ├── openai.py                 # OpenAI provider
│   └── ollama.py                 # Local Ollama
├── integrations/
│   ├── telegram.py               # Telegram bot
│   ├── github.py                 # GitHub webhooks + API
│   └── gitlab.py                 # GitLab webhooks + API
├── models/                       # SQLAlchemy ORM models
├── core/
│   ├── config.py                 # Settings (pydantic-settings)
│   ├── database.py               # DB session factory
│   ├── redis.py                  # Redis client
│   ├── security.py               # JWT, password hashing
│   └── sandbox.py                # Docker sandbox manager
└── main.py                       # FastAPI app factory
```

---

## Database Schema (key tables)

- `users` — id, email, hashed_password, full_name, avatar_url, created_at
- `organizations` — id, name, slug, plan, owner_id
- `org_members` — org_id, user_id, role
- `providers` — id, org_id, name, type, auth_type, credentials (encrypted), rate_limit_until, priority
- `provider_chains` — id, org_id, name, ordered provider list
- `projects` — id, org_id, name, description, repo_url, provider_chain_id, pm_agent_id
- `agents` — id, org_id, name, type, soul, skills[], model_pref, flow_config (JSON)
- `chats` — id, user_id, project_id, title, created_at
- `messages` — id, chat_id, role, content, metadata, created_at
- `integrations` — id, org_id, type (telegram/github/gitlab), config (encrypted)
- `artifacts` — id, chat_id, message_id, filename, content_type, storage_path

---

## Security

- All credentials/tokens encrypted at rest (Fernet symmetric encryption)
- JWTs: 15min access + 7d refresh rotation
- Webhook signatures verified (GitHub: HMAC-SHA256, GitLab: token header)
- Docker sandbox: no host mounts, network limited to egress-only
- CORS restricted to frontend origin
- Rate limiting via Redis (sliding window per user/IP)
