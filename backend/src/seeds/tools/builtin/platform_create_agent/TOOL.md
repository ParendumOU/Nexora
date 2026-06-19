# Create Agent

Create new agent definition in platform for current org.

## Parameters
- `name` (string, required): Display name for agent.
- `description` (string, optional): What agent does.
- `system_prompt` (string, optional): Agent-specific system prompt (Markdown).
- `agent_type` (string, optional): Agent type identifier. Default: `assistant`.
- `skills` (array, optional): Skill keys to attach.
- `tools` (array, optional): Tool keys to enable.
- `soul` (object, optional): Personality fields (tone, style, values, etc.).
- `temperature` (number, optional): LLM temperature 0.0 – 1.0.
- `max_tokens` (integer, optional): Max tokens per res.
- `persona_key` (string, optional): Bootstrap from persona template.
- `context_seed` (object, optional): Seed new agent with context from current session — avoids starting from zero:
  - `inject_context_summary` (string): Free-form summary of current situation, goals, decisions new agent should know. Prepended to agent's system prompt under `## Context from Parent Agent`.
  - `inherit_project_notes` (bool): If `true`, shared project notes (from `chat_notes`) auto-appended to `inject_context_summary`.
  - `initial_task` (string): First task agent expected to work on. Appended to system prompt under `## Initial Assignment`.

## Returns
```json
{ "agent_id": "...", "name": "...", "agent_type": "assistant" }
```

## Notes
- Always allowed; no approval gate.
- Created agents immediately available in org's agent roster.
- Use `platform_create_persona` first if reusable template needed.
