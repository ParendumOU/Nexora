# Tool Architect

Platform engineer specialised in creating and managing tools. Knows the Tools API and can scaffold new tools with documentation files.

## Intended use
Designing and creating tool definitions on the Nexora platform — defining keys, categories, descriptions, and guiding executor and TOOL.md authoring.

## Default capabilities
- **Skills**: none (platform knowledge is embedded in system_prompt)
- **Tools**: http_request

## Key tools used
- `platform_create_tool` — creates tool definitions in the current organisation

## Valid categories
`api` · `code` · `data` · `file` · `integration` · `ai` · `custom` · `web` · `browser` · `git` · `github` · `gitlab` · `docker`

## Customisation notes
- Temperature 0.3 — tool design requires precise parameter schemas and descriptions
- Add `write_file` tool if the agent should also draft executor code or TOOL.md to disk
- Override `system_prompt` to specialise in a specific tool category (e.g. only API integrations, only file tools)
