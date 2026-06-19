# gitlab_api

One tool, many actions. Creds auto-resolved from org token. Returns `{"data": ...}` or `{"error": "..."}`.

## Read — no project_id

### `current_user`
Auth check.
```json
{"action": "current_user"}
```
→ `{"data": {"id": 1234, "username": "...", "name": "...", "email": "...", "is_admin": false, "web_url": "..."}}`

### `list_projects`
Args: `scope` (`member`|`owned`|`starred`|`all`, def `member`), `visibility` (`private`|`internal`|`public`), `search`, `archived` (bool), `min_access_level` (10/20/30/40/50), `group_id` (id or path), `include_subgroups` (bool, def true), `order_by` (def `last_activity_at`), `per_page` (max 100), `max_pages` (def 5).

### `list_groups`
Args: `top_level_only` (bool), `owned` (bool), `min_access_level`, `search`, `per_page`, `max_pages`.

### `list_subgroups`
Args: `group_id` (req), `per_page`, `max_pages`.

### `search`
Args: `scope` (`projects`|`issues`|`merge_requests`|`milestones`|`users`|`blobs`|`commits`), `term` (req).

## Read — require project_id

`project_id`: numeric id or `group/path` (auto URL-encoded).

### `repo_info`
`{"action": "repo_info", "project_id": "group/repo"}`

### `list_issues`
Args: `project_id`, `state` (`opened`|`closed`|`all`, def `opened`), `labels` (comma list), `assignee`, `author`, `search`, `per_page`, `max_pages`.

### `list_mrs`
Args: `project_id`, `state` (`opened`|`closed`|`merged`|`all`), `target_branch`, `source_branch`, `per_page`, `max_pages`.

### `read_file`
Args: `project_id`, `path` (req), `ref` (def `main`).

### `list_branches`
Args: `project_id`, `search`.

### `list_commits`
Args: `project_id`, `ref_name`, `since`, `until`, `path`, `per_page`, `max_pages`.

### `list_pipelines`
Args: `project_id`, `status` (`running`|`pending`|`success`|`failed`|`canceled`|`skipped`), `ref`, `per_page`, `max_pages`.

### `list_members`
Args: `project_id`, `query`, `per_page`, `max_pages`.

## Write — require gitlab_write skill

### `create_issue`
Args: `project_id`, `title` (req), `description`, `labels` (list), `assignee_ids` (list).

### `comment_issue`
Args: `project_id`, `issue_iid` (req), `body` (req).

### `create_mr`
Args: `project_id`, `source_branch`, `target_branch`, `title`, `description`, `remove_source_branch` (bool).

### `trigger_pipeline`
Args: `project_id`, `ref`, `variables` (dict).

### `get_pipeline`
Args: `project_id`, `pipeline_id` (req).
→ `{"id", "status", "ref", "sha", "created_at", "updated_at", "duration", "url"}`

### `list_pipeline_jobs`
Args: `project_id`, `pipeline_id` (req), `scope` (`created`|`pending`|`running`|`failed`|`success`|`canceled`|`skipped`), `per_page`, `max_pages`.
→ `{"jobs": [{"id", "name", "stage", "status", "duration", "failure_reason", "web_url"}], "count", "truncated"}`

### `get_job_log`
Returns last `max_chars` of log (def 8000).
Args: `project_id`, `job_id` (req), `max_chars` (def 8000).
→ `{"job_id", "log", "truncated", "total_chars"}`

### `cancel_pipeline`
Args: `project_id`, `pipeline_id` (req).

### `retry_pipeline`
Args: `project_id`, `pipeline_id` (req).

## Pagination

Auto-paginates to `max_pages * per_page`. `max_pages: 1` = quick peek. Response: `truncated: true` when capped.

## Example

```tool_calls
[{"name": "gitlab_api", "args": {"action": "list_issues", "project_id": "parendum/nexora/nexora", "state": "opened"}}]
```
