## Provider API rules — GitLab / GitHub

- Use `gitlab_api` / `github_api` tools. `http_request` against `gitlab.com/api/*` or `api.github.com` is blocked by the platform — creds only resolve through the dedicated tools.
- `gitlab_api` errors → fix args, don't fall back to HTTP.
- PAT creds → `list_projects`/`list_repos` returns only user memberships. Empty `[]` = real, don't retry.
- Never fabricate project names, IDs, branches, paths, URLs. Use only what API returned.
