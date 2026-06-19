# Google Drive Tool

List, read, create and share files in Google Drive.

## Setup
Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the full JSON content of a Google service account key.
Optionally set `GOOGLE_DRIVE_DELEGATE_EMAIL` to impersonate a user (requires domain-wide delegation).

Create a service account at console.cloud.google.com → IAM → Service Accounts → Create Key (JSON).
Share the target Drive folders/files with the service account email.

## Actions
- `list_files` - List files. Optional: `query` (Drive query string), `folder_id`, `limit`, `order_by`
- `get_file` - Get file metadata. Required: `file_id`
- `read_file` - Read file content (Docs as text, Sheets as CSV, text files inline). Required: `file_id`
- `create_doc` - Create a Google Doc or Sheet. Required: `title`. Optional: `type` (doc/sheet), `content`, `folder_id`
- `upload_file` - Upload a file. Required: `name`, `content`. Optional: `content_type`, `folder_id`
- `share_file` - Share a file with a user. Required: `file_id`, `email`. Optional: `role` (reader/writer/owner), `notify`

## Query syntax (list_files)
```json
{"action": "list_files", "query": "name contains 'report' and mimeType='application/vnd.google-apps.document'"}
```