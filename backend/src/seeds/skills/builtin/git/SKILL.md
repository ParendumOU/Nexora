# Git

Interact with local Git repos: clone, commit, push, pull, diff, log, status.

## Common workflows

### Inspect repo
```tool_calls
[{"name": "git_status", "args": {"path": "/workspace/my-repo"}}]
```

### Commit changes
```tool_calls
[
  {"name": "git_commit", "args": {"path": "/workspace/my-repo", "message": "feat: add new endpoint"}},
  {"name": "git_push", "args": {"path": "/workspace/my-repo"}}
]
```

## Guidelines
- Run `git_status` before committing
- Meaningful commit msgs, Conventional Commits format
- Never force-push to main/master without explicit user confirmation
