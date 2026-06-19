# Create Skill

Create new skill definition in platform for current org.

## Parameters
- `key` (string, required): Unique skill identifier (snake_case).
- `name` (string, required): Human-readable skill name.
- `description` (string, optional): Capability this skill grants.
- `content` (string, optional): SKILL.md content injected into agent system prompt when skill active.
- `config` (object, optional): Arbitrary skill config merged at runtime.

## Returns
```json
{ "skill_id": "...", "key": "...", "name": "..." }
```

## Notes
- Always allowed; no approval gate.
- Custom skills stored under `seeds/skills/custom/` — override builtin skills of same key.
- Attach to agents via `platform_create_agent` or Agents settings UI.
