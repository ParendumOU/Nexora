# GitHub Write

Create, modify resources in GitHub. Use `github_api`.

## Canonical tool: `github_api`

### Write actions
- `create_issue` — open issue (args: repo, title, body, labels, assignees)
- `comment_issue` — post comment (args: repo, issue_number, body)
- `create_pr` — open PR (args: repo, head, base, title, body, draft)
- `commit_file` — create/update single file (args: repo, path, branch, content, message)
- `trigger_workflow` — manual dispatch (args: repo, workflow_id, ref, inputs)

## Legacy tools

`github_create_issue`, `github_create_pr`, `github_commit_file` — back-compat only. Prefer `github_api`.

## Guidelines

- Confirm before creating public issues/PRs.
- Descriptive titles, context in body.
- `commit_file`: backend auto-resolves existing `sha` — no need to fetch it.

## Example

```tool_calls
[{"name": "github_api", "args": {"action": "create_issue", "repo": "myorg/myapp", "title": "feat: user export", "body": "Users want CSV export…"}}]
```
