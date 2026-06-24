# Changelog

All notable changes to Nexora core. Newest first; one `## <version>` heading per release.
The release CI extracts the section matching the pushed tag as the GitHub Release notes.

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
