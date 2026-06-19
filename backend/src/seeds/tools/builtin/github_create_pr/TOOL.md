# GitHub Create Pull Request

Create PR in GitHub repo.

## Parameters
- `owner` (string, required): repo owner
- `repo` (string, required): repo name
- `title` (string, required): PR title
- `head` (string, required): head branch (source)
- `base` (string, required): base branch (target)
- `body` (string, optional): PR description (Markdown)
- `draft` (boolean, optional): create as draft PR (default: false)

## Returns
```json
{ "number": 13, "url": "https://github.com/owner/repo/pull/13" }
```
