# Changelog

All notable changes to Nexora core. Newest first; one `## <version>` heading per release.
The release CI extracts the section matching the pushed tag as the GitHub Release notes.

## 1.3.0

The **Autonomy Layer**: agents can now pursue durable objectives, verify their own
work, and self-direct — plus a redesigned reasoning UI. Everything that changes
behaviour is behind a flag (default off), so upgrades are safe.

### Autonomy
- **Durable goals** (migration 061 — `goals` + `milestones`; `tasks` gain
  optional goal/milestone links). A `Goal` is decomposed into ordered `Milestone`s;
  goal progress and auto-completion roll up from milestone status. REST API at
  `/api/goals` (CRUD + milestones) and agent tools `goal_create`, `goal_update`,
  `goal_read`, `milestone_add`, `milestone_status` so an agent can plan and track
  objectives across chats. Status synonyms (e.g. "completed" → done) accepted.
- **Acceptance-criteria verification** (`TASK_VERIFICATION_ENABLED`, default off): a
  task carrying explicit acceptance criteria (or inheriting a milestone's
  success_criteria) is judged by an LLM critic before it is marked done; on failure
  the feedback is bounced back into the sub-agent loop (bounded retries) instead of
  declaring success.
- **Proactive goal tick** (`AUTONOMY_TICK_ENABLED`, default off): a periodic,
  budget-aware sweep that recomputes goal progress and decides the next actionable
  milestone per active goal.
- **Deterministic turn completion**: a turn is terminal when it issues no tool calls
  (the `<final/>` marker is now just how that's persisted). A turn that merely
  *announces* a next action ("I'll read it now…") without acting is detected as a
  hallucinated promise and nudged to actually act, instead of stopping.

### Governance (`#235`)
- **Tool risk tiers** — every tool is classified read / write / external / exec, and
  an operator can hard-deny a tier (`DENY_EXEC_TOOLS`, `DENY_EXTERNAL_TOOLS`).
- **Per-org token budget** (`ORG_TOKEN_BUDGET`, 0 = unlimited): a rolling-window
  token tally that gates autonomous spending (never hard-blocks an interactive chat).

### Reasoning UI
- The chat now renders model reasoning as a collapsible **"Thought · N steps"** panel
  outside the answer bubble (like the agent-actions card): live "Thinking…" → folded
  "Thought for Ns" when done, per-thought folding (only the latest stays open while
  live), auto-scroll, and tool-call JSON shown as compact chips.
- The "Agent · N actions" card now persists across a page refresh and auto-collapses
  when it finishes.

### Notes
- Idempotent goals migration (tolerates the startup `create_all`). Run
  `alembic upgrade head` after upgrading.
- Try the autonomy stack by enabling, in order: `NATIVE_TOOLS_ENABLED` → acceptance
  criteria + `TASK_VERIFICATION_ENABLED` → `AUTONOMY_TICK_ENABLED` (+ `ORG_TOKEN_BUDGET`).

## 1.2.0

Large orchestration, provider, and reasoning pass. Backward-compatible — new
behaviours that change topology or the wire format are behind flags that default off.

### Providers & models
- Explicit multi-account failover with durable per-account health/circuit state
  (`state`/`cooling_until`/`consecutive_failures`); `Retry-After` / ratelimit-reset
  headers parsed for accurate cooldowns; typed rate-limit detection (Gemini 429,
  Bedrock throttling codes) replacing substring sniffing.
- CLI provider rate-limit now fails over instead of aborting the whole chain.
- Per-agent `temperature` / `max_tokens` are now actually applied at inference, and
  an agent can bind a `ModelProfile` (capability) — provider selection decoupled
  from the agent definition.
- Native function calling (flag `NATIVE_TOOLS_ENABLED`, default off): Anthropic /
  OpenAI-compatible / Gemini tool calls are converted back into the existing
  tool-call fence, so the rest of the pipeline is unchanged. Argument schemas added
  for 28 core tools, with required-argument validation.

### Reasoning / Modes
- Flash / Think / Deep now drives provider-native reasoning (Anthropic extended
  thinking, OpenAI `reasoning_effort`, Gemini thinking budget), capability-gated per
  model with a prompt-prefix fallback.
- Provider reasoning is surfaced as `<think>` blocks; the chat renders them as a
  collapsible, per-thought, auto-scrolling panel.

### Orchestration & runtime
- Unified the five duplicated turn loops into one shared turn engine.
- Durable background-run queue + `runner` worker + cross-worker concurrency governor
  (flag `RUN_QUEUE_ENABLED`, default off).
- Provider-stream inactivity timeout; bounded pub/sub queues with drop-oldest
  backpressure; SSE turns now broadcast for WS/SSE parity; chat presence moved to
  Redis (multi-worker correct); unified sub-delegation depth.

### Security
- Tool permissions enforced for every tool against the agent's toolset (not just
  platform builtins), with an opt-in default-deny; phantom (non-executable) tools are
  no longer advertised.

### Fixes
- Stop "Agent is writing…" hanging after a finished turn; relay sub-agent results
  reliably; scrub leaked tool-call JSON tails; live chat now matches the saved
  message on reload; sanitize chat titles; tolerant UTF-8 BOM seed loading;
  word-boundary-aware prompt templating.

## 1.1.3

- Removed the in-core Python (Typer) `cli/` — dead code superseded by the standalone
  [NexoraCLI](https://github.com/ParendumOU/Nexora-CLI) (Go TUI). It was never built,
  installed, tested, or referenced by the backend, Docker images, or CI.

## 1.1.2

- Removed the stale top-level `docs/` folder (legacy "AgenticChats" architecture/provider/
  agent/roadmap/CLI notes — outdated and unreferenced). Real docs live in the NexoraDocs site;
  quick-start is in the README.

## 1.1.1

- First public GitHub release of the OSS core.
- Added project README with quick-start, feature overview, and client links.
- CI now publishes a clean, squashed one-commit-per-version snapshot to GitHub on each tag
  (internal history stays private; internal docs and vendored reference projects excluded).

## 1.1.0

- Knowledge base / RAG (pgvector), semantic memory search, multimodal image input.
- SSE streaming endpoint as a WebSocket alternative.
- Mobile device pairing (`/auth/device/*`), full-platform backup/restore, instance migration.
- CLI sub-agent observability, local tool execution, Telegram channels.

## 1.0.0

- First tagged release: multi-tenant agent orchestration, ~46 providers, ~90 tools,
  marketplace client, recovery engine.
