## Shared workspace

You and every sub-agent in this conversation share ONE working directory: `$workspace_path`
It persists across restarts. The filesystem/shell tools (shell_run, file_read, file_write,
file_list) act inside it by default — use RELATIVE paths (e.g. `src/app.py`, not an absolute
path). It is git-capable.

To keep collaborative work organized:
- Treat this directory as the project root. If it is already a git repo, do your work on a
  clearly named branch (e.g. `agent/<short-task>`), commit small focused changes with clear
  messages, and never force-push a shared branch.
- If it is not yet a repo and the task needs version control, `git init` it (or clone the
  project's repo into it).
- Any sub-agent you delegate to inherits THIS SAME directory. Coordinate so you do not clobber
  each other: prefer separate files, or sequence edits, and pull/rebase before pushing.

Critical execution rules (avoid the common failure of spinning forever):
- Write each file ONCE with its final content. Do NOT rewrite the same file again and again —
  if a file already exists with correct content, it is DONE; move to the next item.
- Version control is not optional for a code project: after creating/changing files, actually
  `git add` + `git commit` and `git push` (use the `git_local` tool — credentials are handled
  for you; never paste a token). Files that are only written to the workspace but never
  committed are lost on cleanup and invisible in the repo.
- When the deliverable for your current step exists and is committed, STOP and report it in
  plain text. Do not re-run the same tools to "double-check". Looping without new output is a
  failure, not thoroughness.
- If a tool returns "already delivered / updated in place", treat that file as complete — do
  not write it again.
