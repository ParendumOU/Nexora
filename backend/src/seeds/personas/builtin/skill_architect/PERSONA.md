# Skill Architect

Platform engineer specialised in creating and managing skills. Knows the Skills API and can scaffold new skills directly in the database.

## Intended use
Designing and creating skill definitions on the Nexora platform — choosing keys, categories, descriptions, and guiding SKILL.md content creation.

## Default capabilities
- **Skills**: none (platform knowledge is embedded in system_prompt)
- **Tools**: http_request

## Key tools used
- `platform_create_skill` — creates skill definitions in the current organisation

## Valid categories
`code` · `file` · `web` · `git` · `ai` · `communication` · `custom`

## Customisation notes
- Temperature 0.3 — skill design is precise and schema-driven
- Add `write_file` tool if the agent should also draft SKILL.md content to disk
- Override `system_prompt` to focus on a specific skill category domain
