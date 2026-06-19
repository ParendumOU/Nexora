# Spawn Team

Create full team of agents in one call — combines persona templates.

## Parameters
- `members` (array, required): List of role specs.
  - `persona_key` (string, required): Persona template key (e.g. `developer`, `qa_engineer`, `devops`, `researcher`, `designer`).
  - `count` (integer, optional): Agents of this role to create. Default: 1.
  - `name_prefix` (string, optional): Prefix before role name (e.g. `Backend` → `Backend Developer 1`).
  - `overrides` (object, optional): Field overrides applied to each created agent (soul, skills, tools, system_prompt, etc.).
- `team_name` (string, optional): Label for team — returned in res for reference.

## Returns
```json
{
  "team_name": "...",
  "agents": [
    { "agent_id": "...", "name": "Backend Developer 1", "persona_key": "developer" }
  ]
}
```

## Notes
- Each agent created with skills/tools from persona template.
- Use `overrides` per member spec to customise individual agents without rebuilding from scratch.
- Available persona keys depend on seeds loaded for org.
