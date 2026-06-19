## Provider API rules — GitLab / GitHub

- Use `gitlab_api` / `github_api` tools. **Never** `http_request` against `gitlab.com/api/*` or `api.github.com` — creds not resolved → 401.
- `gitlab_api` errors → fix args, don't fall back to HTTP.
- PAT creds → `list_projects`/`list_repos` returns only user memberships. Empty `[]` = real, don't retry.
- Never fabricate project names, IDs, branches, paths, URLs. Use only what API returned.
