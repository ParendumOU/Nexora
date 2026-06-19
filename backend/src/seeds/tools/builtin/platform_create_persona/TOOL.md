# Create Persona

Create new persona definition in platform for current org.

## Parameters
- `key` (string, required): Unique persona identifier (snake_case), e.g. `backend_developer`.
- `name` (string, required): Human-readable persona name.
- `description` (string, optional): Role description.
- `soul` (object, optional): Default personality fields (tone, style, values, expertise, etc.).
- `skills` (array, optional): Default skill keys for agents created from this persona.
- `tools` (array, optional): Default tool keys for agents created from this persona.
- `system_prompt` (string, optional): Base system prompt for this persona role.
- `temperature` (number, optional): Default LLM temperature 0.0 – 1.0.
- `agent_type` (string, optional): Default agent type identifier.

## Returns
```json
{ "persona_id": "...", "key": "...", "name": "..." }
```

## Notes
- Always allowed; no approval gate.
- Personas = reusable templates — use `team_spawn` or `platform_create_agent` with `persona_key` to instantiate agents.
- Custom personas stored under `seeds/personas/custom/` — override builtin personas of same key.
