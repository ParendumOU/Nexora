# GitLab Write

Create, modify resources in GitLab. Use `gitlab_api` for everything.

## Canonical tool: `gitlab_api`

### Write actions
- `create_issue` — open issue (args: project_id, title, description, labels, assignee_ids)
- `comment_issue` — post note (args: project_id, issue_iid, body)
- `create_mr` — open MR (args: project_id, source_branch, target_branch, title, description)
- `trigger_pipeline` — trigger CI on ref (args: project_id, ref, variables)

## Legacy tools

`gitlab_create_issue`, `gitlab_create_mr`, `gitlab_trigger_pipeline` — back-compat only, delegate to same backend. Prefer `gitlab_api`.

## Guidelines

- Confirm with user before triggering pipelines on protected branches.
- Use draft MRs while work in progress.

## Example

```tool_calls
[{"name": "gitlab_api", "args": {"action": "create_mr", "project_id": "mygroup/myapp", "title": "feat: export", "source_branch": "feat/export", "target_branch": "main"}}]
```
