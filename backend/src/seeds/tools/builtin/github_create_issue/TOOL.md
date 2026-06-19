# GitHub Create Issue

Create issue in GitHub repo.

## Parameters
- `owner` (string, required): repo owner
- `repo` (string, required): repo name
- `title` (string, required): issue title
- `body` (string, optional): issue body (Markdown)
- `labels` (array, optional): label names to apply
- `assignees` (array, optional): GitHub usernames to assign

## Returns
```json
{ "number": 43, "url": "https://github.com/owner/repo/issues/43" }
```
