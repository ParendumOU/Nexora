# Contributing to Nexora

Thanks for your interest in improving Nexora! This is the free, MIT-licensed OSS core of the
platform. Contributions of all sizes are welcome — bug reports, docs, and code.

## Ground rules

- Be respectful — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- Found a security issue? **Do not** open a public issue — see [`SECURITY.md`](SECURITY.md).
- This repo is **pure platform** — no billing, licensing, or paywall logic. Commercial features
  live in the downstream NexoraCloud product, not here.

## Getting set up

```bash
git clone https://github.com/ParendumOU/Nexora.git
cd Nexora
cp .env.example .env          # set SECRET_KEY + ENCRYPTION_KEY (see SETUP.md)
make dev                      # backend :8000, frontend :3000, nginx :8080
docker compose exec backend alembic upgrade head
```

First visit with no users → `/setup` to create the admin account. Full guide in
[`SETUP.md`](SETUP.md).

> ⚠ **Never run `npm` on the host.** Run all frontend commands inside Docker:
> `docker compose exec frontend pnpm <cmd>`. Use `pnpm`, never `npm`.

## Development conventions

- **Backend:** read config via `get_settings()` (never `os.environ`). New entity → model +
  register in `models/__init__.py` → Alembic migration → router. No prompt strings in Python —
  use `seeds/prompts/*.md`.
- **Frontend:** TypeScript strict, App Router, API calls via `lib/api.ts`, no hardcoded URLs.
- **Migrations:** set `down_revision` to the current head; `alembic heads` must show exactly one.

## Submitting changes

1. Branch off `main`.
2. Use [Conventional Commits](https://www.conventionalcommits.org): `feat(scope):`, `fix(scope):`, `chore:`.
3. Run the backend tests (`pytest backend/tests/`) and frontend type-check where relevant.
4. Open a PR with a clear description of *what* and *why*. Link any related issue.

We review PRs on a best-effort basis. Smaller, focused PRs merge faster.
