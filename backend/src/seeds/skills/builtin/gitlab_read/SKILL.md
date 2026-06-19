# GitLab Read

Read access: projects, issues, MRs, files, pipelines, members.

## Tool: `gitlab_api`

ALWAYS use `gitlab_api` — credentials auto-resolved. NEVER call `http_request` against `gitlab.com/api/...`.

### Common actions
- `current_user` — verify auth
- `list_projects` — visible repos (`scope`: member/owned/starred/all)
- `list_groups` — accessible namespaces
- `list_subgroups` — children of parent group
- `repo_info` — single project metadata
- `list_issues` / `list_mrs` — per-project
- `read_file` — file at ref
- `list_branches` / `list_commits` / `list_pipelines`
- `search` — global across projects/issues/MRs/commits/users/blobs

## Legacy tools

`gitlab_repo_info`, `gitlab_list_issues`, `gitlab_list_mrs`, `gitlab_read_file` — back-compat only. Prefer `gitlab_api` → chain multiple actions in one response.

## Requirements

PAT stored in Settings → Integrations → GitLab. Self-hosted: credential carries `base_url`.

PAT scope = human who issued it (not service account, not admin):
- `list_projects scope=member` → ONLY projects PAT owner is member of.
- `list_groups` → ONLY groups owner belongs to.
- Empty `[]` = PAT genuinely has no membership. Do NOT retry with guessed names.

## Anti-hallucination

Always use real API responses verbatim. Never invent project names, slugs, ids, namespaces, branches, paths, URLs, or "probable" repos. Inventory smaller than expected → say so, suggest checking PAT scope.

## Example

```tool_calls
[
  {"name": "gitlab_api", "args": {"action": "current_user"}},
  {"name": "gitlab_api", "args": {"action": "list_projects", "scope": "member", "visibility": "private", "max_pages": 10}}
]
```
