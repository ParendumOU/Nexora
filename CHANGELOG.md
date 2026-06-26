# Changelog

All notable changes to Nexora core. Newest first; one `## <version>` heading per release.
The release CI extracts the section matching the pushed tag as the GitHub Release notes.

> **Format rule (keep it uniform, see v1.1.0):** each version is a FLAT bullet list of
> shipped items. NO intro paragraph, NO `###` sub-sections, NO `**bold**`, and never use
> an em dash (use a normal `-` or rephrase). The docs changelog
> (docs.nexora.parendum.com/changelog) renders release notes as PLAIN TEXT
> (`white-space: pre-line`), so anything fancy shows up as literal junk; plain `-` bullets
> are the only thing that looks right. Keep each line short and direct.

## 1.11.4

- Fix delegated sub-agent work stalling when the durable run queue is enabled but no runner process is consuming it: the platform now detects whether a runner is alive and otherwise runs the work in-process, so delegation never silently disappears.
- Tasks an agent creates now inherit their conversation's project, so they group on the project board and delegated runs get the right repository and workspace context.
- The built-in Project Manager can now list the available agents, so it routes each task to a suitable specialist instead of guessing.

## 1.11.3

- The create-repository destination picker is now a fast lazy tree: it loads your accounts and top-level groups instantly and lets you drill into subgroups on demand, in their natural order, instead of slowly listing everything flat.

## 1.11.2

- Creating a repository from a project now uses a proper picker dialog: search and select the destination personal account, organization, or group, instead of a cramped dropdown.

## 1.11.1

- Fix a production frontend build failure introduced in 1.11.0 (the new Workspaces settings tab referenced the wrong toast and store modules).

## 1.11.0

- Agents can now run real git in the shared workspace: a new local git tool clones, branches, commits and pushes a live working tree, authenticating with the project's stored GitHub/GitLab credential without ever exposing the token.
- Projects gain commit and push rules: a short note you write in the project Repository tab is shown to every agent working in that project's workspace, so they follow your branch naming and commit conventions.
- Create a repository straight from a project: pick a stored credential, choose the GitHub org or GitLab group to put it in, name it, and it is created and linked in one step.
- New superuser Workspaces settings tab to see every agent workspace with its size and git status, and delete stale ones.

## 1.10.0

- Risky-command approvals gain an "Always allow similar" action: approving a held command with it stops re-prompting for commands with the same content for the rest of the conversation (sub-agents included), while different commands still ask.
- New optional shared agent workspace: when enabled, an agent and all of its sub-agents work inside one persistent directory per project (or per conversation when there is no project), so a team can build a real git-backed codebase together, and the directory survives restarts.

## 1.9.0

- Provider-native function calling, system-prompt caching, parallel read-only tools, and event-driven sub-agent delegation are now on by default after production validation; each can still be turned off with its setting.
- Nested sub-agent delegation is now bounded at every level: a delegating agent frees its concurrency slot while it waits for its children, and the children run within the normal global, per-agent, and per-organization limits instead of off-pool, so deep fan-out can no longer overrun a worker.
- Cancelling a turn now takes effect within about two seconds even when the model is mid-response and streaming nothing back, not only between chunks.

## 1.8.0

- Knowledge base and agent memory search now use a real vector index (pgvector) for faster, more accurate semantic results, with an automatic fallback when the extension is not available.
- Agents can delegate to a sub-agent and receive its answer reliably: peer messaging resolves the right organization in every context, replies no longer fail, and a completed task automatically answers the waiting agent.
- New built-in KB Researcher agent: a read-only research specialist you can delegate knowledge base and web lookups to without giving the caller direct knowledge base access.
- A safety guard stops weaker models from looping the same tool forever and forces them to deliver the answer.
- Provider-native function calling is available for the built-in tools (opt-in), with argument schemas for almost all of them.
- Optional system-prompt caching reuses the static part of the prompt across turns to cut token cost (opt-in, Anthropic).
- WebSocket connections now carry the auth token off the URL (via subprotocol or header) so it no longer appears in server or proxy logs.
- Sub-agent delegation can wait on an event instead of polling the database (opt-in), and independent read-only tools in a turn can run in parallel (opt-in).
- Cancelling a turn now takes effect within about a second, even during a long tool call.
- Local tool execution and presence now work correctly across multiple backend workers.
- Chat cleanups: no more empty assistant bubbles or duplicate replies on weaker models, the activity card no longer blinks or jumps and now sits above the answer, failed tools stay marked failed after reload, a sub-chat no longer lists itself, and the live view now matches exactly what a refresh shows.
- All feature, autonomy, and tool-governance flags are documented in .env.example.

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
