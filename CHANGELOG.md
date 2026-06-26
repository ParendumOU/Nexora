# Changelog

All notable changes to Nexora core. Newest first; one `## <version>` heading per release.
The release CI extracts the section matching the pushed tag as the GitHub Release notes.

> **Format rule (keep it uniform, see v1.1.0):** each version is a FLAT bullet list of
> shipped items. NO intro paragraph, NO `###` sub-sections, NO `**bold**`, and never use
> an em dash (use a normal `-` or rephrase). The docs changelog
> (docs.nexora.parendum.com/changelog) renders release notes as PLAIN TEXT
> (`white-space: pre-line`), so anything fancy shows up as literal junk; plain `-` bullets
> are the only thing that looks right. Keep each line short and direct.

## 1.19.2

- Deleting a conversation now also stops its autonomous run. Previously a deleted chat could keep working in the background (the run kept being dispatched and came back on refresh); deleting now pauses the run and halts its in-flight work, so removing a chat truly ends it.

## 1.19.1

- Fixed stopped autonomous runs coming back after a restart even with auto-resume disabled. The cause was the proactive autonomy loop (which dispatches active goals every minute): stopping a run from one of its sub-conversations did not pause the goal that lives at the top of the run, so the loop kept reviving it. Stopping now pauses the goal across the whole run (sub-conversation and the chain above it), and the autonomy loop skips any run whose conversation was just stopped.
- Added a "Pause all autonomy" button (in the hierarchy view) and matching API to stop every autonomous run in the workspace at once. Paused runs stay stopped across restarts until resumed.

## 1.19.0

- Agents now follow a strict communication-discipline rule that cuts wasted tokens: no preamble or filler, short status lines, no meetings/pitches/status ceremony unless asked, and terse one or two line messages between agents. This reduces both the output agents generate and the input other agents receive from them.
- The shared thread-memory block injected into every agent turn is now capped (the rest stays queryable on demand), so a long-running conversation no longer keeps inflating the per-turn prompt size.

## 1.18.2

- Fixed a frontend build failure introduced in 1.18.0 (a missing import broke the production build). No behavior change.

## 1.18.1

- Fixed the backend becoming unresponsive (502 errors, dropped connections, "Couldn't load data", failed chat deletes) on instances with very large conversation trees. The query that decides which conversations show a "working" spinner is now depth-guarded so it can never run away on a malformed tree, has a hard time limit, and is cached for a few seconds so a burst of updates can't overload the database.
- Added a safeguard and an off switch for auto-resuming autonomous runs after a restart: at most a few runs resume per startup, and AUTOPILOT_RECOVERY_ENABLED=false disables auto-resume entirely (useful if many runs are overloading an instance). Stopping a run still keeps it stopped.

## 1.18.0

- A stopped autonomous run no longer comes back to life after a server restart or rebuild. Stopping (Stop or Kill All) now pauses the run, and startup recovery leaves paused runs alone instead of reviving them (which had also caused a fresh branch to appear on restart).
- When a run is stopped, the conversation now shows a clear "Execution stopped" note, and if the run can be continued it offers an optional Resume button that picks up the current milestone where it left off. You can also just send a message to carry on.

## 1.17.0

- Stopping a run (the chat Stop button or "Kill All" in the hierarchy view) is now fast even on a huge conversation tree: cancellation collects the whole tree in one query and signals every conversation in a single batched round-trip instead of one-by-one.
- When you press Stop or Kill All, the working spinner is replaced by the normal chat view instantly, without waiting for the server to finish cancelling.
- Deleting a chat from the sidebar now removes it immediately (it reappears only if the server rejects the delete).
- New multi-select in the chat sidebar: a "Select" button turns chats into checkboxes so you can pick several and delete them all at once.

## 1.16.0

- The chat sidebar loads fast again on instances with very large conversation trees: it now loads only top-level conversations and pulls sub-conversations on demand, instead of loading every sub-chat up front (a single autonomous run had grown to nearly 2000).
- The conversation hierarchy view now opens showing only the conversations still in progress, with a "Show all" toggle to load the full tree on demand, and it builds the tree in one query instead of one per node, so it opens quickly even with thousands of sub-chats.
- A rate limit no longer fails a turn when it will clear in moments: if every account is rate-limited with a short reset (such as an OpenAI per-minute token burst), the platform waits for the soonest reset and retries the chain instead of giving up. Short resets reported in the provider's message are now read accurately.
- Accept/Reject in the repository panel no longer shows a raw "405 Method Not Allowed". Merge waits for the host to finish its mergeability check, reuses an already-open merge request, and reports a clear message when a branch genuinely cannot be auto-merged.

## 1.15.6

- The main conversation and every conversation above a working sub-agent now show a "Sub-agents working…" indicator while a deeply nested sub-agent is active, instead of looking idle. The indicator clears on its own shortly after the deep work stops.

## 1.15.5

- The Docker tools an agent can use (list containers, view logs, build an image, run a command) now actually work. They were listed but had no implementation, so an agent that tried them got stuck repeating a failing "tool not available" call. They run against Docker directly, and the run command keeps the safety guard that blocks anything that could take down the platform.

## 1.15.4

- Fixed the repository panel's changed-files list showing rows of "?" with no names or counts. The compare endpoint now returns each changed file with its path, status, and added/removed line counts (for both GitHub and GitLab) instead of just a filename, so the list, diff view, and per-file stats render correctly.
- The repository file tree now shows the branch you are viewing (the selected agent branch when there is one) instead of always the base branch, so the explorer reflects the agent's work rather than appearing almost empty.

## 1.15.3

- The repository panel inside a conversation no longer crashes the whole app ("Application error: a client-side exception") when it hits unexpected data. It is now wrapped in an error boundary that shows a contained, retryable message with the actual error, and the file tree tolerates malformed entries instead of throwing.

## 1.15.2

- Fixed the chat sidebar failing to load with a repeated "Couldn't load data" error. A single message whose stored data contained an invalid NUL character made the conversation-list query fail, which blanked the entire sidebar and left conversations stuck loading. The query now tolerates such a message, and messages are stripped of these characters when saved so it cannot recur.
- Fixed autonomous runs not starting later milestones because their tasks were created without an owner (a not-null constraint failed). The owner is now resolved from the conversation, so multi-milestone Autopilot runs proceed past the first milestone.

## 1.15.1

- Fixed repeated "Couldn't load data" errors and chats not loading on a busy conversation. The task list was running several database queries per task, so the once-per-second refresh on a conversation with hundreds of tasks could exhaust the database connection pool and make every request time out. Task lists are now loaded in a fixed number of queries regardless of how many tasks there are.

## 1.15.0

- Autonomous runs no longer balloon into hundreds of conversations. Agent broadcasts are now bounded by a per-run budget and a fan-out cap, so a team can still coordinate but a broadcast can no longer trigger an exponential storm of new conversations. A targeted message to one agent is never capped, and both limits are configurable.

## 1.14.4

- Fixed an error that made updating a task or completing a plan step fail with "cannot access local variable timezone"; these now work reliably during autonomous runs.
- Agents can now create agents and issues without hitting a database type error: numeric and text fields the model fills in (an agent's max tokens or temperature, an issue's title or project) are normalized to the right type instead of being rejected.
- Raised the shell command timeout from 60 to 300 seconds so real installs and builds (pnpm install, docker build) are no longer killed partway through.

## 1.14.3

- When an autonomous run is resumed after a server restart, the conversation now posts a short note saying it is continuing, so the self-recovery is visible in the chat instead of only in the logs.

## 1.14.2

- An autonomous Autopilot run now survives a backend restart or redeploy: on startup the platform resumes any in-progress goal, re-dispatching the current milestone's remaining work or advancing to the next milestone, so a deploy no longer kills a run that was in progress.
- Moving from one milestone to the next is now guarded so it cannot happen twice at once, preventing duplicate follow-up tasks when two tasks finish at the same moment.

## 1.14.1

- Agents can no longer run a shell command that takes down the platform itself (stopping, killing, removing or restarting containers, rebooting, or mass-killing processes); they can still bring their own project up with docker compose. This fixes the backend restarting in the middle of an autonomous run.
- The shell command timeout is configurable and was raised so builds and installs do not time out instantly; a timed-out command is now stopped cleanly.

## 1.14.0

- Approval requests for risky commands now appear in the top-level conversation, so you can approve or deny every sub-agent's action from one place without opening each sub-chat.
- The YOLO and Autopilot toggles now stick: they are remembered per conversation across refreshes and chat switches, apply to all of a conversation's sub-agents, and save the moment you flip them.
- Fixed the look of the YOLO and Autopilot toggle switches.

## 1.13.1

- A tool call that keeps failing with the same arguments is now blocked after two identical failures, so a weaker model can no longer get stuck repeating the same failing action in a loop.

## 1.13.0

- New Autopilot mode (per-chat toggle): describe a project and the platform plans it once into a roadmap of milestones and small tasks, then builds it autonomously by assigning each task to a capable agent, running them, verifying acceptance, and advancing milestone by milestone until done. The orchestration is driven by code, so it works even with smaller models.

## 1.12.0

- Delegated tasks are now routed to a capable agent automatically: when an agent creates a task without naming who should do it, the platform picks the best-fit specialist by skills and tools (with a sensible fallback), so delegation no longer depends on the model knowing agent names.

## 1.11.7

- Clearer error when an agent guesses a non-existent GitHub/GitLab API action such as create: the message now points it to commit_file or the git_local workspace flow, so a model is less likely to loop on it.

## 1.11.6

- The built-in Infrastructure Manager agent can now use local git, so a delegated agent can clone, branch, commit, and push a project's repository instead of only writing files that never reach the repo.
- Stronger guidance for agents working in a shared workspace: write each file once, commit and push with git, and stop when the deliverable is done, which prevents weaker models from rewriting the same file in a loop.

## 1.11.5

- The Files panel no longer fills with duplicates when an agent rewrites a file: re-writing the same path updates one entry in place, files keep their folder structure so the panel shows a real folder tree of what the agents are building, and the per-file toast spam during generation is gone.

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
