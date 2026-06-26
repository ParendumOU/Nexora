# Git (local workspace)

Run the real `git` CLI inside the shared workspace (the persistent directory you and
your sub-agents share). Use this to clone a repo, branch, commit and push an actual
working tree — as opposed to the API-only `git` tool. Credentials are resolved
automatically from the project/org; never pass or ask for a token.

Requires the shared workspace to be enabled. Network actions (clone/push/pull/fetch)
need the project to have a repository URL and a stored GitHub/GitLab credential.

## Parameters

| Param | Type | Required | Notes |
|---|---|---|---|
| `action` | string | yes | See actions below |
| `branch` | string | conditional | name for `branch`/`checkout`; target for `push`/`pull` (defaults to current) |
| `message` | string | for commit | commit message |
| `add_all` | bool | no | `commit`: stage everything first (`git add -A`) |
| `paths` | array | no | `add`: paths to stage (default `.`) |
| `path` | string | no | `diff`: limit to a path |
| `staged` | bool | no | `diff`: show staged changes |
| `repo_url` | string | no | `clone`: override the project repo |
| `limit` | int | no | `log`: commit count (default 20) |

## Actions
`clone` | `init` | `status` | `branch` | `checkout` | `add` | `commit` | `push` | `pull` | `fetch` | `log` | `diff` | `current_branch`

## Typical flow
1. `clone` (or `init`) to set up the working tree in the workspace.
2. `branch` with a clear name like `agent/<short-task>` to isolate your work.
3. Edit files with `file_write` (relative paths land in the workspace).
4. `commit` with `add_all: true` and a clear message.
5. `push` to publish the branch. Open a PR/MR with the `git` tool's `merge` action.

Keep commits small and focused. Never force-push a shared branch. If others may be
working in the same repo, `pull` before you `push`.
