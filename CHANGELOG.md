# Changelog

All notable changes to Nexora core. Newest first; one `## <version>` heading per release.
The release CI extracts the section matching the pushed tag as the GitHub Release notes.

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
