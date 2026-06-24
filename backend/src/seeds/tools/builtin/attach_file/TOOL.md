# Attach File

Attach a file you produced to the current conversation. The file is registered as a
chat attachment: it appears in the **Files** panel and the user can download it with a
single click.

Use this after you write a deliverable with `file_write` (or generate one any other way)
and want the user to be able to grab it — an HTML/CSS component, a report, a generated
document, an export, etc. Don't paste large file bodies into the chat; attach them.

## Parameters
- `path` (string, required): Path to the file to attach. In a normal (web/cloud) chat this
  is the path inside the agent workspace where you wrote it. In a CLI local-execution chat
  it is the path on the user's own machine.
- `name` (string, optional): Display filename shown in the Files panel. Defaults to the
  basename of `path`.

## Returns
```json
{
  "attached": true,
  "file_id": "…",
  "name": "card.html",
  "size_bytes": 5120,
  "download_url": "/api/chats/<chat_id>/files/<file_id>/content",
  "local_path": "/home/user/card.html"
}
```
`download_url` is the one-click download link surfaced in the Files panel. `local_path` is
only present in CLI local-execution chats, where the file already lives on the user's host.

## Notes
- Text deliverables (HTML, CSS, JS, Markdown, JSON, CSV, …) always attach cleanly.
- In CLI local mode the file is read back from the user's host; if it can't be read as
  text (binary), the tool returns the local path only and the file is not copied into the
  conversation.
