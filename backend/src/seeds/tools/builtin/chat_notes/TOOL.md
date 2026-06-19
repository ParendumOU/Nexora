## chat_notes — Shared Chat Scratchpad

Shared notes tied to root conversation. All sub-agents in same chat tree read/write same notes.

**Use for:**
- Record findings, decisions, intermediate results → other agents build on them.
- Build inventory or summary across parallel sub-agent runs.
- Leave context for orchestrator about what was discovered.

**Actions:**
- `read` — return current notes (no content needed).
- `write` — replace notes entirely.
- `append` — add text to end (preserves existing content).

**Examples:**
```json
{"action": "read"}
{"action": "append", "content": "- Repo nexora: private, 12 branches\n- Repo docs: public"}
{"action": "write", "content": "## GitLab Inventory\n- nexora: private\n- docs: public"}
```

Notes persist for conversation lifetime — visible in context of all agents in chat tree.
