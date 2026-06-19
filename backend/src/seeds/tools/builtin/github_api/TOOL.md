# github_api

One tool, many actions. Creds auto-resolved from org token. Returns `{"data": ...}` or `{"error": "..."}`.

## Read — no repo required

### `current_user`
```json
{"action": "current_user"}
```
→ `{"data": {"login": "...", "id": 123, "name": "...", "email": "...", "html_url": "..."}}`

### `list_repos`
Args: `scope` (`affiliations` def — owner+collaborator+org_member; `owned`, `member`, `all`), `visibility` (`private`|`public`|`all`), `type` (`all`|`owner`|`public`|`private`|`member`), `affiliation` (CSV: `owner,collaborator,organization_member`), `sort` (def `pushed`), `per_page` (max 100), `max_pages` (def 5).

### `list_orgs`
No args.

### `list_org_repos`
Args: `org` (req), `type` (`all`|`public`|`private`|`forks`|`sources`|`member`), `per_page`, `max_pages`.

### `search`
Args: `scope` (`repositories`|`code`|`issues`|`commits`|`users`), `q` (req), `sort`, `order`, `per_page`, `max_pages`.

## Read — require repo

`repo`: `owner/name`.

### `repo_info`
`{"action": "repo_info", "repo": "owner/name"}`

### `list_issues`
Args: `repo`, `state` (`open`|`closed`|`all`, def `open`), `labels` (CSV), `assignee`, `creator`, `sort`, `per_page`, `max_pages`.

### `list_prs`
Args: `repo`, `state` (`open`|`closed`|`all`), `base`, `head`, `sort`, `per_page`, `max_pages`.

### `read_file`
Args: `repo`, `path` (req), `ref` (def `main`).

### `list_branches`
Args: `repo`, `protected` (bool).

### `list_commits`
Args: `repo`, `sha`, `path`, `author`, `since`, `until`, `per_page`, `max_pages`.

### `list_workflows`
Args: `repo`.

### `list_runs`
Args: `repo`, `workflow_id`, `branch`, `status` (`queued`|`in_progress`|`completed`|`success`|`failure`|`cancelled`), `per_page`, `max_pages`.

## Write — require github_write skill

### `create_issue`
Args: `repo`, `title` (req), `body`, `labels` (list), `assignees` (list).

### `comment_issue`
Args: `repo`, `issue_number` (req), `body` (req).

### `create_pr`
Args: `repo`, `head` (req), `base` (req), `title` (req), `body`, `draft` (bool).

### `commit_file`
Single-file branch commit.
Args: `repo`, `path`, `branch`, `content` (raw text), `message`.

### `trigger_workflow`
Manual dispatch.
Args: `repo`, `workflow_id` (id or filename), `ref` (def `main`), `inputs` (dict).

## Pagination

Auto-paginates to `max_pages * per_page`. Response: `truncated: true` when capped.

## Example

```tool_calls
[{"name": "github_api", "args": {"action": "list_issues", "repo": "anthropics/anthropic-sdk-python", "state": "open"}}]
```
