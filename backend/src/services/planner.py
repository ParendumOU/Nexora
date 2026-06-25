"""Backlog planner / prioritizer (GitLab #237, Autonomy epic #238).

Turns a flat backlog (open goals + tasks) into an ORDERED, capacity-bounded plan
instead of reactive FIFO dispatch. Pure + unit-tested; the autonomy tick and the
backlog API consume it.

Ordering rule (deterministic):
  1. Only items that are actionable now (status open + all blockers satisfied).
  2. Higher priority first (numeric, higher = sooner).
  3. Then oldest first (FIFO within a priority — fairness / no starvation).
Items blocked by something not yet done are held out (with the blocker noted).
"""
from __future__ import annotations

_OPEN = {"pending", "queued", "in_progress", "active", "blocked"}
_DONE = {"completed", "done", "skipped", "cancelled", "failed"}


def prioritize_backlog(items: list[dict], capacity: int | None = None) -> dict:
    """Order a backlog. Each item: {id, kind?, priority?, created_at?, status?,
    blocked_by?: [ids]}. Returns {"plan": [...], "blocked": [...]} where `plan` is
    the actionable items in execution order (capped at `capacity` when given) and
    `blocked` lists items waiting on unfinished dependencies.
    """
    by_id = {it.get("id"): it for it in items if it.get("id")}
    done_ids = {i for i, it in by_id.items() if (it.get("status") or "").lower() in _DONE}

    actionable: list[dict] = []
    blocked: list[dict] = []
    for it in items:
        status = (it.get("status") or "pending").lower()
        if status in _DONE:
            continue
        blockers = [b for b in (it.get("blocked_by") or []) if b in by_id and b not in done_ids]
        if blockers:
            blocked.append({**it, "_waiting_on": blockers})
        else:
            actionable.append(it)

    # higher priority first, then oldest (created_at asc); stable for missing fields.
    actionable.sort(key=lambda it: (
        -int(it.get("priority") or 0),
        str(it.get("created_at") or ""),
    ))

    plan = actionable[: capacity] if (capacity and capacity > 0) else actionable
    return {"plan": plan, "blocked": blocked}
