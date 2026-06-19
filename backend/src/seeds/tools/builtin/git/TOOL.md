# Git

Interact with project repo — GitHub or GitLab. Credentials auto-resolved — never include tokens.

## Parameters

| Param | Type | Required | Notes |
|---|---|---|---|
| `action` | string | yes | See actions below |
| `repo_url` | string | no | Defaults to project repo |
| `branch` | string | no | Default: `main` |
| `path` | string | conditional | Required for `read_file`, `write_file` |
| `content` | string | conditional | Required for `write_file` |
| `message` | string | no | Commit msg for `write_file`; default: `"Update via platform"` |
| `from_branch` | string | no | Source for `create_branch`; default: `main` |
| `base` | string | conditional | Required for `compare`, `merge` |
| `head` | string | conditional | Required for `compare`, `merge` |
| `state` | string | no | `list_issues`: `open`/`opened`/`closed`/`all`; default `open`. GitHub+GitLab spellings accepted. Empty result → no matching issues, not error. Missing open issues → retry with `state: "all"`. |
| `limit` | int | no | `get_tree` only: max entries (default 300, max 500) |

## Actions
`list_branches` | `get_tree` | `read_file` | `write_file` | `create_branch` | `delete_branch` | `list_commits` | `compare` | `list_issues` | `merge`

## Examples

```json
{ "action": "get_tree", "branch": "main" }
```

```json
{ "action": "read_file", "path": "src/main.py", "branch": "main" }
```

```json
{ "action": "write_file", "path": "src/utils.py", "content": "# new file\n", "branch": "feature/my-branch", "message": "Add utils module" }
```

```json
{ "action": "compare", "base": "main", "head": "feature/my-branch" }
```
