from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from functools import lru_cache

_WEAK_SECRETS = {
    "changeme", "changeme_in_production",
    "super-secret-key-change-in-production",
    "your-secret-key-here", "your-fernet-key-here", "",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "Nexora"
    environment: str = "production"
    log_level: str = "info"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://nexora:changeme@localhost:5432/nexora"

    # Connection pool — tune for concurrent sub-agent workloads
    db_pool_size: int = 20        # base connections kept alive
    db_max_overflow: int = 40     # extra burst connections (total cap = pool_size + max_overflow)
    db_pool_timeout: int = 60     # seconds to wait for a free connection before error
    db_pool_recycle: int = 1800   # recycle connections after 30 min to avoid stale-conn errors

    # Redis
    redis_url: str = "redis://:changeme@localhost:6379/0"

    # Security
    secret_key: str = "super-secret-key-change-in-production"
    encryption_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    @model_validator(mode="after")
    def _reject_weak_secrets_in_production(self) -> "Settings":
        if self.environment != "production":
            return self
        errors = []
        if self.secret_key in _WEAK_SECRETS or len(self.secret_key) < 32:
            errors.append("SECRET_KEY must be a strong random value (≥32 chars) in production")
        if self.encryption_key in _WEAK_SECRETS:
            errors.append("ENCRYPTION_KEY must be set in production (use Fernet.generate_key())")
        if "changeme" in self.database_url:
            errors.append("DATABASE_URL contains default password 'changeme' — set POSTGRES_PASSWORD")
        if "changeme" in self.redis_url:
            errors.append("REDIS_URL contains default password 'changeme' — set REDIS_PASSWORD")
        if errors:
            raise ValueError("Insecure configuration for production:\n  " + "\n  ".join(errors))
        return self

    # CORS — stored as comma-separated string, parsed at runtime
    cors_origins_str: str = Field(
        default="http://localhost,http://localhost:3000",
        alias="CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        from urllib.parse import urlparse
        origins = []
        for s in self.cors_origins_str.split(","):
            s = s.strip()
            if s and urlparse(s).scheme in ("http", "https"):
                origins.append(s)
        return origins

    # Auth providers (CLI-based OAuth)
    auth_providers_dir: str = "/auth_providers"

    # File uploads
    upload_dir: str = "/app/uploads"
    max_upload_size_mb: int = 100

    # Docker
    docker_host: str = "unix:///var/run/docker.sock"
    workspace_base: str = "/workspaces"
    sandbox_image: str = "python:3.12-slim"

    # Proactive autonomy tick (GitLab #234, Autonomy epic #238). A periodic sweep that
    # advances active goals (picks the next pending milestone, recomputes progress).
    # OFF by default. When only the tick is enabled it maintains goal state + plans;
    # actual agent spawning requires autonomy_dispatch_enabled too (gated on #235).
    autonomy_tick_enabled: bool = False
    autonomy_tick_interval_minutes: int = 5
    autonomy_tick_max_goals: int = 20        # safety cap on goals processed per tick
    # Autonomous dispatch (#234 last mile): the tick SPAWNS an agent toward the next
    # milestone (gated additionally by budget #235 + risk tiers on its tools). Requires
    # autonomy_tick_enabled too. OFF by default — opt-in for unattended runs.
    autonomy_dispatch_enabled: bool = False
    autonomy_max_dispatch_per_tick: int = 1  # milestones launched per sweep

    # Governance: tool risk policy (GitLab #235, Autonomy epic #238). Each tool is
    # classified into a risk tier (read | write | external | exec); these flags let an
    # operator hard-deny a whole tier (e.g. for an unattended/autonomous deployment).
    # Default off → every tier allowed (existing behaviour). Always-allowed coordination
    # tools (task_create, log_entry, goal_*, …) are never gated by risk.
    deny_exec_tools: bool = False        # block exec tier (shell_run, code_*, docker_*)
    deny_external_tools: bool = False    # block external tier (slack, jira, http_request, s3, k8s, …)
    # Human-in-the-loop approval (#235): a tool whose risk tier is at/above this
    # threshold is held for human approval before it runs. "" / "off" = never (default).
    # Values: read | write | external | exec. Always-allowed coordination tools exempt.
    require_approval_tier: str = ""
    # Per-org token budget over a rolling window (#235). 0 = unlimited (default, no
    # tracking/enforcement). When > 0, LLM usage is tallied in Redis and over_budget()
    # gates the proactive autonomy dispatch (interactive chat is never hard-blocked).
    org_token_budget: int = 0
    budget_window_hours: int = 24

    # Task verification / acceptance-criteria loop (GitLab #233, Autonomy epic #238).
    # OFF by default + only runs when a task/milestone has explicit acceptance
    # criteria, so existing behaviour is unchanged until enabled.
    task_verification_enabled: bool = False
    max_verification_retries: int = 2        # times a failing sub-agent turn is bounced back with feedback

    # Concurrency — sub-agent execution limits
    max_concurrent_agents: int = 2           # global cap per worker process
    max_concurrent_agents_per_org: int = 4   # cross-worker cap per org (Redis-coordinated)
    tasks_per_batch: int = 2                 # max tasks dispatched per _run_delegated_tasks call
    max_subdelegation_depth: int = 4         # max agent→sub-agent nesting depth

    # Run queue / runners (GitLab #219) — durable background-run execution.
    # OFF by default: background runs (sub-agent dispatch, orchestrator resumes,
    # webhook events) keep using in-process asyncio.create_task. When enabled they
    # are XADD'd to a Redis Stream and executed by dedicated `runner` workers, with
    # a cross-worker concurrency governor and event-driven sub-agent resume.
    run_queue_enabled: bool = False
    # Event-driven sub-agent delegation (GitLab #218). When true, a delegating
    # parent waits on a Redis pub/sub child-done signal (waking promptly, ~no DB
    # load) instead of polling Postgres once per second for up to 300s. The
    # semaphore-bypass for children + the slot the parent holds while waiting are
    # unchanged (slot release is the runner phase). Default ON since v1.9.0 (Redis
    # is always present); set false to restore the legacy 1s busy-poll.
    event_driven_delegation: bool = True
    run_queue_stream: str = "nexora:runs"
    run_queue_group: str = "runners"
    runner_concurrency: int = 4              # concurrent runs per runner worker
    runner_block_ms: int = 5000              # XREADGROUP block timeout
    runner_claim_min_idle_ms: int = 120000   # reclaim a pending run abandoned by a dead runner after this

    # Proactive proposals
    proposal_auto_approve_confidence: float = 0.85  # confidence >= this → auto-execute without human review

    # Recovery engine
    max_task_retries: int = 3                # max retry attempts before moving task to dead-letter
    circuit_breaker_threshold: int = 3       # consecutive failures before circuit opens (5 min TTL)
    heartbeat_timeout_minutes: int = 5       # minutes before a stale heartbeat triggers task recovery

    # Native tool calling (GitLab #214). When on, API adapters that support it
    # (Anthropic, OpenAI-compatible) send the agent's schema-backed tools to the
    # provider's native function-calling API and convert the structured tool calls
    # back into the existing ```tool_calls fence, so the rest of the pipeline
    # (parser, executor, frontend) is unchanged. Tools without a declared schema
    # stay on the text-fence path. Default ON since v1.9.0; set false to force the
    # legacy text-fence path for every tool/provider.
    native_tools_enabled: bool = True

    # Prompt caching (GitLab #220). When true, the platform-context builder inserts
    # a cache breakpoint after the large static tool/intro block, and the Anthropic
    # adapter marks that stable prefix with cache_control: ephemeral so it is reused
    # across tool-resume turns instead of re-billed every iteration. The breakpoint
    # sentinel is stripped from every non-caching provider so it can never leak into
    # a prompt — a no-op for non-Anthropic paths. Default ON since v1.9.0; set false
    # for a byte-identical prompt with no cache_control split.
    prompt_cache_enabled: bool = True

    # Parallel read-tier tool execution (GitLab #229). When true, side-effect-free
    # read-tier tool calls in a single turn (file_read, board_read, knowledge_search,
    # github/gitlab read, …) are computed concurrently up-front and consumed by the
    # normal sequential loop, cutting latency on read-heavy turns. Events, ordering,
    # and gating are unchanged. Default ON since v1.9.0; set false for the fully
    # sequential path.
    parallel_tool_calls_enabled: bool = True

    # Tool permissions (GitLab #222)
    tools_default_deny: bool = False         # when true, an agent with NO configured tools is
                                             # deny-all (only always-allowed + its skills/local
                                             # tools pass) instead of the default allow-all

    # Provider failover (per-account health/circuit — GitLab #216)
    provider_failure_circuit_threshold: int = 5   # consecutive non-rate failures before an account is marked "exhausted"
    provider_exhausted_cooldown_seconds: int = 300  # how long an "exhausted" account is skipped before being retried

    # Streaming
    provider_stream_idle_timeout_seconds: int = 300  # abort a turn if the provider emits no
                                             # chunk for this long (hung stream guard, #223). 0 = off.
    cancel_poll_interval_seconds: float = 2.0  # max time a chunkless provider call ignores a user
                                             # cancel (#223). The stream consumer races each chunk
                                             # against this slice and checks the cancel flag between
                                             # slices, so cancel takes effect within ~this many
                                             # seconds even mid-call. 0 = legacy (cancel only checked
                                             # every Nth chunk, so a chunkless call ignores it).
    pubsub_queue_maxsize: int = 2000         # per-subscriber pub/sub queue cap; a stuck/slow
                                             # consumer drops OLDEST events instead of growing
                                             # memory unbounded (GitLab #225). 0 = unbounded.
    max_truncation_continuations: int = 3    # times to auto-continue a reply cut off at max_tokens (0 disables)
    max_empty_retries: int = 2               # retry the SAME provider when it streams nothing (flaky weak models
                                             # return empty completions intermittently); 0 disables. Safe — only
                                             # retries when zero content was yielded, so no duplicate output.

    # Anti-spin: max consecutive tool-resume turns with no progress (no file delivered,
    # no task completed, no <final/>) before the orchestrator is halted with an honest
    # message instead of looping forever. 0 disables the breaker.
    max_resume_spin: int = 8

    # Registration gating
    require_invite: bool = False  # set True to require a signup invite token to register

    # Email (optional — leave smtp_host empty to disable)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Nexora <noreply@parendum.com>"
    smtp_tls: bool = True
    app_url: str = "http://localhost:3000"  # used in email links

    # Email verification (optional — graceful no-op when SMTP not configured)
    require_email_verification: bool = False

    # Cloud billing worker (optional — set in nexora-cloud deployments)
    billing_worker_url: str = ""

    # Nexora Gateway — for OSS update check (optional)
    nexora_gateway_url: str = ""

    # Base URL the CLI subprocess uses to POST hook callbacks back to this
    # backend (the CLI runs inside the backend container → loopback default).
    cli_hook_ingest_url: str = "http://127.0.0.1:8000"

    # Security: gate CLI bypass-permission flags for all three CLI providers:
    #   Claude  → --permission-mode bypassPermissions
    #   Gemini  → --yolo (auto-approve all tool calls)
    #   Codex   → --dangerously-bypass-approvals-and-sandbox
    # Default false — operators must explicitly opt in. When false these flags are
    # omitted entirely and each CLI runs in its default (safe) permission mode.
    allow_cli_bypass_permissions: bool = False

    # Auto-memory: agents auto-write a markdown memory note when a task completes.
    # Platform default; per-agent override via agent.soul["auto_memory"] (bool).
    auto_memory_notes: bool = True

    # Sub-agent fan-out cap FALLBACK: max concurrently-active sibling tasks under one
    # parent (pending/queued/in_progress) when the calling agent has no per-agent
    # max_subagents set. Prevents a runaway orchestrator spawning dozens at once.
    # 0 = unlimited.
    max_tasks_per_parent: int = 12

    # Per-ROOT-conversation spawn caps. The per-parent fan-out cap above only bounds
    # SIBLINGS under one parent; a recursive loop evades it by spreading spawns across
    # many sub-chats (each a fresh parent), so the TOTAL under one root conversation is
    # otherwise unbounded — this is exactly how a runaway loop once created ~227 chats.
    # Both are keyed on the root chat id (walk Chat.parent_chat_id to the top). 0 = off.
    #   - cumulative: total sub-agent tasks a single root conversation may EVER spawn.
    #   - rate: sub-agent tasks a single root may spawn within max_spawn_rate_window_seconds.
    max_subagents_per_root: int = 60
    max_spawn_rate_per_root: int = 20
    max_spawn_rate_window_seconds: int = 60

    # Tool dependency isolation: a tool/skill shipping a requirements.txt runs in
    # its own per-pack venv (keyed by requirements hash → multi-version isolation).
    # Set false to forbid venv provisioning (locked-down/offline deployments).
    tool_envs_enabled: bool = True
    tool_envs_dir: str = "/app/tool_envs"

    # CLI provider rate limiting (sliding 1-hour window per user / per org)
    cli_rate_limit_per_user_per_hour: int = 60
    cli_rate_limit_per_org_per_hour: int = 300

    # External marketplace
    nexora_marketplace_url: str = "https://marketplace.nexora.parendum.com"

    # HTTP tool allowlist (SSRF guard) — comma-separated base URLs; empty = unrestricted
    http_tool_allowed_origins_str: str = Field(default="", alias="HTTP_TOOL_ALLOWED_ORIGINS")

    @property
    def http_tool_allowed_origins(self) -> list[str]:
        origins = []
        for s in self.http_tool_allowed_origins_str.split(","):
            s = s.strip().rstrip("/")
            if s:
                origins.append(s)
        return origins

    # Integrations (optional)
    telegram_bot_token: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""
    gitlab_app_id: str = ""
    gitlab_app_secret: str = ""
    gitlab_webhook_secret: str = ""

    # OAuth social login (optional — leave empty to disable)
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
