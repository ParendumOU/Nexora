# Changelog

All notable changes to Nexora core. Newest first; one `## <version>` heading per release.
The release CI extracts the section matching the pushed tag as the GitHub Release notes.

> **Format rule (keep it uniform, see v1.1.0):** each version is a FLAT bullet list of
> shipped items. NO intro paragraph, NO `###` sub-sections, NO `**bold**`, and never use
> an em dash (use a normal `-` or rephrase). The docs changelog
> (docs.nexora.parendum.com/changelog) renders release notes as PLAIN TEXT
> (`white-space: pre-line`), so anything fancy shows up as literal junk; plain `-` bullets
> are the only thing that looks right. Keep each line short and direct.

## 1.7.0

- Structured audit log for sensitive actions (member changes, invites, backup export/import/migrate) with a superuser and org-admin viewer.
- Incoming custom webhooks can now verify an HMAC signature of the request body, not just the path secret.
- Rate limits added to marketplace import and install, git proxy file and tree fetches, and new WebSocket connections.
- First-run registration is hardened against a race that could let two concurrent signups both skip the invite requirement.
- Integration config is validated against a per-type allowlist, and user backup import now enforces field size limits.
- Pagination added to users, memories, notifications, proposals, and knowledge base files; old notifications are trimmed automatically.
- Faster organization, knowledge base, and integration list endpoints by removing per-row extra queries.
- New database indexes for the recovery scan, scheduler, and proposals, plus trigram-accelerated chat and message search.
- Schedules now retry on failure and surface errors instead of failing silently, reject overlapping runs, validate the cron expression when you save, and support a per-schedule concurrency limit and timeout.
- Global search now spans agents, tools, skills, projects, and knowledge bases, not just chats and messages.
- Marketplace import now installs the declared dependencies of skill, tool, and persona packages, not only agents and packs.
- API keys can be scoped to read-only or restricted to specific organizations.
- Notifications can be delivered by email or Telegram for events missed while you were offline.
- Knowledge base search accepts a relevance threshold to drop low-quality matches.

## 1.6.0

- Outcome tracking and decision log: agents record what an action or goal achieved (with optional KPI) and the decisions they made, and can query that history to learn.
- Outcomes are recorded automatically when a goal completes.
- Persistent agent org chart: assign durable roles and areas of ownership, with escalation paths.
- Backlog planner: a prioritised plan across all open goals and tasks (priority, then oldest first, dependency-blocked items held out) instead of reactive FIFO.
- Turn control is now a deterministic state machine in code (resume, wait, nudge, final), not prompt instructions.

## 1.5.0

- Human-in-the-loop tool approval: tools at/above a configurable risk tier are held for review instead of running (flag, default off).
- Approve or deny inline in the chat or from the Approvals page; on approve the tool runs and the agent responds.
- Approval card is collapsible and shows the exact command + console-formatted output.
- Per-chat YOLO toggle to skip the prompt, like the CLI.
- Agents now wrap command output, code, logs and JSON in fenced code blocks across web, CLI and Telegram.

## 1.4.0

- Autonomous dispatch: the proactive tick can spawn a goal's owner agent toward its next milestone, runs the work under the origin chat, and rolls completion back up (flag, default off).
- New goal_delete tool to clean up goals.
- Files panel is now a folder tree with per-file download and delete; agents can save into folders; broken attachment names fixed.
- Sidebar shows a flat chat list with a spinner on chats that have work running.
- A turn now survives leaving the chat: it keeps running server-side and reconnecting catches up live.
- Open panels (sub-agents, right side) are remembered per chat.
- The "Agent actions" card shows live, not only after a refresh.
- Orchestrator nudges agents that promise an action without doing it; stray think tags and leaked tool-call JSON no longer render.

## 1.3.0

- Durable goals: Goal to Milestones with progress roll-up, REST API and agent tools to plan and track objectives across chats.
- Acceptance-criteria verification: an LLM critic checks a task before it's marked done (flag, default off).
- Proactive autonomy tick that advances active goals (flag, default off).
- Governance: tool risk tiers with per-tier deny, plus a per-org token budget.
- Deterministic turn completion; agents that promise an action are nudged to actually do it.
- Reasoning shown as a collapsible "Thought" panel; the "Agent actions" card persists across refresh and auto-collapses.

## 1.2.0

- Multi-account provider failover with per-account health tracking and rate-limit cooldowns.
- Per-agent temperature/max_tokens; agents can bind a model profile.
- Native function calling for Anthropic, OpenAI and Gemini (flag, default off).
- Flash / Think / Deep now drives real provider reasoning, shown as think blocks.
- Unified turn engine, durable background run queue, Redis presence, SSE/WebSocket parity.
- Tool permissions enforced per agent with opt-in default-deny.
- Fixes: stuck "Agent is writing", leaked tool-call JSON, live-vs-saved mismatch, chat titles.

## 1.1.3

- Removed the in-core Python CLI (dead code, superseded by the standalone NexoraCLI).

## 1.1.2

- Removed the stale top-level docs folder; real docs live on the NexoraDocs site.

## 1.1.1

- First public GitHub release of the OSS core.
- Added the project README with quick-start, feature overview and client links.
- CI publishes a clean squashed snapshot to GitHub on each tag.

## 1.1.0

- Knowledge base / RAG (pgvector), semantic memory search, multimodal image input.
- SSE streaming endpoint as a WebSocket alternative.
- Mobile device pairing, full-platform backup/restore, instance migration.
- CLI sub-agent observability, local tool execution, Telegram channels.

## 1.0.0

- First tagged release: multi-tenant agent orchestration, ~46 providers, ~90 tools, marketplace client, recovery engine.
