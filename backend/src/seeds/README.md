# Seed Library

This directory contains all platform seed data — skills, tools, personas, and agents — as versioned files on disk. The loader (`loader.py`) scans this tree at startup and serves it through the API.

## Directory layout

```
seeds/
  skills/
    builtin/<key>/
      skill.json      ← manifest (key, name, description, category, is_builtin)
      SKILL.md        ← documentation injected into agent context
    custom/<key>/     ← user-added seeds (same structure)
  tools/
    builtin/<key>/
      tool.json       ← manifest (key, name, description, category, env_vars, …)
      TOOL.md
    custom/<key>/
  personas/
    builtin/<key>/
      persona.json    ← manifest (key, name, icon, soul, default_skills, …)
      PERSONA.md
    custom/<key>/
  agents/
    builtin/<key>/
      agent.json      ← manifest (name, agent_type, skills, tools, soul, …)
      AGENT.md        ← used as system_prompt if system_prompt not set in JSON
    custom/<key>/
  system/
    system.json       ← platform-level config (feature flags, defaults)
```

## `is_builtin` vs `builtin/` directory

| Location | `is_builtin` in JSON | Meaning |
|----------|----------------------|---------|
| `builtin/` | `true` | Platform-provided, read-only in the UI |
| `builtin/` | `false` | Shipped with the platform but user-editable |
| `custom/`  | `false` | User-created via UI or ZIP import |

## Loader

`loader.py` caches results in-process. Call `reload()` after any ZIP import to invalidate the cache.

## Import / Export

Seeds can be packaged as ZIP archives and imported/exported via:

- `GET /api/seeds/export` — download full catalog as ZIP
- `POST /api/seeds/import` — upload ZIP to add/replace seeds
- `GET /api/skills/builtin/{key}/export` — export a single skill
- `GET /api/tools/builtin/{key}/export` — export a single tool
- `GET /api/personas/builtin/{key}/export` — export a single persona

ZIP format: `{type}/{custom|builtin}/{key}/{files…}`

## Adding a new builtin seed

1. Create `seeds/{type}/builtin/{key}/`
2. Add the manifest JSON and optional markdown file
3. Restart the backend (or call `loader.reload()`) to pick it up
4. Run `seed_all()` to propagate DB records to all orgs if needed
