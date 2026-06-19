# GitLab Repo Info

Fetch metadata for GitLab project.

## Environment Variables
- `GITLAB_TOKEN`: GitLab personal access token

## Parameters
- `project_id` (string, required): project ID or URL-encoded path (e.g. `group/project`)
- `gitlab_url` (string, optional): GitLab instance URL (default: `https://gitlab.com`)

## Returns
```json
{
  "id": 123,
  "name": "my-project",
  "description": "...",
  "stars": 10,
  "forks": 2,
  "default_branch": "main"
}
```
