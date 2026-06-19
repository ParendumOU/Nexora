# GitHub Read

Read access: repos, issues, PRs, files, branches, workflows, runs.

## Canonical tool: `github_api`

ALWAYS use `github_api` — credentials auto-resolved, raw token never exposed. NEVER call `http_request` against `api.github.com` directly.

### Common actions
- `current_user` — confirm auth works
- `list_repos` — repos affiliated with token (scope: affiliations/owned/member/all)
- `list_orgs` — orgs you belong to
- `list_org_repos` — repos within specific org
- `repo_info` — single repo metadata
- `list_issues` / `list_prs` — per-repo
- `read_file` — file at ref
- `list_branches` / `list_commits`
- `list_workflows` / `list_runs` — GitHub Actions
- `search` — global search

See `github_api` tool docs for full arg list.

## Legacy tools

`github_repo_info`, `github_list_issues`, `github_list_prs`, `github_read_file` — back-compat only. Prefer `github_api`.

## Requirements

GitHub credential in platform credential store with `repo` read scope.

Credential = Personal Access Token (PAT) — scoped to human user who issued it:
- `list_repos scope=affiliations` → ONLY repos PAT owner owns, collaborates on, or is org member of. Random public repos NOT included.
- `list_orgs` → ONLY orgs PAT owner belongs to.
- Empty results = PAT genuinely has no affiliation. Do NOT retry guessing org names.

## Anti-hallucination

ALWAYS use real API responses verbatim. NEVER invent:
- Repo names, owners, ids, branch names, file paths, URLs, topics.
- "Probable" repos based on context.
- Repos user "should" have — if API didn't return them, not accessible to this PAT.

Inventory smaller than expected → say so plainly, suggest checking PAT scopes (`repo`, `read:org`). Never pad list.

## Example — inventory

```tool_calls
[
  {"name": "github_api", "args": {"action": "current_user"}},
  {"name": "github_api", "args": {"action": "list_repos", "scope": "owned", "visibility": "private", "max_pages": 5}}
]
```
