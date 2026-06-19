## Git Tool — Repository Access

`git` tool = ONLY correct way to access GitHub/GitLab repos. Credentials auto-resolved — never pass tokens.

### Actions

| Action | Required params | What it does |
|---|---|---|
| `get_tree` | `repo_url` | List all files/dirs (default limit 300) |
| `read_file` | `repo_url`, `path` | Read file contents |
| `write_file` | `repo_url`, `path`, `content`, `message` | Commit file change |
| `list_branches` | `repo_url` | List branches |
| `create_branch` | `repo_url`, `branch`, `from_branch` | New branch |
| `list_commits` | `repo_url`, `branch?` | Recent commits |
| `compare` | `repo_url`, `base`, `head` | Diff two refs |
| `list_issues` | `repo_url` | Open issues |
| `merge` | `repo_url`, `branch` | Merge into default |

`repo_url` = full HTTPS clone URL. `branch` defaults to repo default.

### Example

```tool_calls
[{"name": "git", "args": {"action": "write_file", "repo_url": "https://github.com/org/myrepo", "path": "src/main.py", "content": "...", "message": "fix: update main", "branch": "fix/my-branch"}}]
```

### NEVER

- `http_request` against GitHub/GitLab APIs — credential mismatch, rate limits, CF blocks.
- `shell_run` to clone/pull — no filesystem.
- Repo name as tool name (`nexora-frontend` etc.) — tool is always `git`.
- Invent "Git Proxy" or intermediate service.
- Pass tokens/credential IDs — platform auto-resolves. On credential error use `request_from_parent`.
