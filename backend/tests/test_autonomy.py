"""Proactive autonomy tick — decision engine (GitLab #234)."""
from src.services.autonomy import select_next_actions


def _g(gid, ms):
    return {"goal_id": gid, "milestones": [{"id": f"{gid}-{i}", "status": s, "position": i} for i, s in enumerate(ms)]}


def test_picks_first_pending_milestone():
    actions = select_next_actions([_g("g1", ["pending", "pending"])])
    assert actions == [{"goal_id": "g1", "milestone_id": "g1-0", "already_running": False}]


def test_skips_done_picks_next():
    actions = select_next_actions([_g("g1", ["done", "pending", "pending"])])
    assert actions[0]["milestone_id"] == "g1-1" and actions[0]["already_running"] is False


def test_in_progress_surfaced_as_running():
    actions = select_next_actions([_g("g1", ["done", "in_progress", "pending"])])
    assert actions == [{"goal_id": "g1", "milestone_id": "g1-1", "already_running": True}]


def test_all_done_goal_yields_nothing():
    assert select_next_actions([_g("g1", ["done", "skipped"])]) == []


def test_no_milestones_skipped():
    assert select_next_actions([{"goal_id": "g1", "milestones": []}]) == []


def test_multiple_goals():
    actions = select_next_actions([
        _g("g1", ["done", "pending"]),
        _g("g2", ["in_progress"]),
        _g("g3", ["done"]),
    ])
    by_goal = {a["goal_id"]: a for a in actions}
    assert by_goal["g1"]["milestone_id"] == "g1-1" and not by_goal["g1"]["already_running"]
    assert by_goal["g2"]["already_running"] is True
    assert "g3" not in by_goal  # all done → no action


def test_respects_position_order():
    # positions out of array order → sorted by position
    g = {"goal_id": "g1", "milestones": [
        {"id": "b", "status": "pending", "position": 2},
        {"id": "a", "status": "pending", "position": 1},
    ]}
    assert select_next_actions([g])[0]["milestone_id"] == "a"
