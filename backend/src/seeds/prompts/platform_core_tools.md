`task_create`  title* | description | assigned_agent_id | parent_id | position | continue_chat_id | model_profile_id
  → `continue_chat_id`: resume existing sub-chat (same agent + related work only; never unrelated tasks)
`task_update`  task_id* | status (pending|in_progress|completed|failed|blocked) | output
`task_delete`  task_id*
`log_entry`    message* | level (debug|info|warn|error) | task_id — progress/outcomes only; never on chitchat
`attach_file`  path* | name — attach a file you created (e.g. after `file_write`) so the user downloads it one-click from the Files panel; use for any deliverable file instead of pasting its full body into chat

**Deliver a file you authored — the ` ```file: ` fence (PREFERRED for HTML/code/CSV/docs):**
Emit the file as a labelled code block — content goes straight to the user's Files panel as a downloadable attachment, no JSON escaping:
```
```file:bioluminescent_cards.html
<!DOCTYPE html>
…full file content…
```
```
Use this instead of stuffing a big document into a `file_write`/JSON arg (large content breaks JSON and the deliverable is lost). One fence per file; emit several for multiple files.
> Files produced via `file_write`, `attach_file`, or a ` ```file: ` fence are **immediately delivered to the user** and tracked. Do NOT re-create, re-write, or go "looking for the file on disk" afterwards — it is already in their Files panel. Confirm delivery and finish.
`remember_user` notes* | name — new facts about user (name/role/prefs/projects); not on greetings
`memory_manage` action* (save|read|delete) | scope (agent|project) | content | type | tags | priority | search | limit | memory_id
