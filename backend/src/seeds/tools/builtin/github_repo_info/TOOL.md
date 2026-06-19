# GitHub Repo Info

Fetch metadata for GitHub repo.

## Environment Variables
- `GITHUB_TOKEN`: personal access token or GitHub App token

## Parameters
- `owner` (string, required): repo owner (user or org)
- `repo` (string, required): repo name

## Returns
```json
{
  "full_name": "owner/repo",
  "description": "...",
  "stars": 1234,
  "forks": 56,
  "default_branch": "main",
  "topics": ["python", "api"]
}
```
