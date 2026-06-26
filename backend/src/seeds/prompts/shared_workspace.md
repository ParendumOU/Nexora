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
