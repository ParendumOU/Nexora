"""Hierarchy 'Active only' filter — a stopped/failed run must drop out of the default view.

Regression for the runaway where a cancelled tree (every task -> failed/dead/blocked) kept
showing under 'Active only' because failed counted as active and dead/blocked were not folded
into the failed bucket.
"""
import uuid
import pytest
from sqlalchemy import select


async def _seed_tree(db, email="fixture@example.com"):
    from src.models.user import User
    from src.models.chat import Chat
    from src.models.task import Task

    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    root = Chat(id=str(uuid.uuid4()), user_id=user.id, title="root run")
    dead_child = Chat(id=str(uuid.uuid4()), user_id=user.id, parent_chat_id=root.id, title="all dead")
    live_child = Chat(id=str(uuid.uuid4()), user_id=user.id, parent_chat_id=root.id, title="still pending")
    db.add_all([root, dead_child, live_child])
    await db.flush()
    # dead_child: terminal failures only (failed + dead + blocked) — must be hidden.
    for st in ("failed", "dead", "blocked"):
        db.add(Task(id=str(uuid.uuid4()), chat_id=dead_child.id, title=f"t-{st}", status=st))
    # live_child: one pending task — genuinely unfinished, must stay.
    db.add(Task(id=str(uuid.uuid4()), chat_id=live_child.id, title="t-pending", status="pending"))
    await db.commit()
    return root.id, dead_child.id, live_child.id


@pytest.mark.asyncio
async def test_active_only_hides_failed_subtree(client, auth_headers, db):
    root_id, dead_id, live_id = await _seed_tree(db)

    r = await client.get(f"/api/chats/{root_id}/hierarchy?active_only=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {n["id"] for n in body["nodes"]}

    assert root_id in ids            # anchor always kept
    assert live_id in ids            # pending work -> active -> kept
    assert dead_id not in ids        # all-terminal -> hidden
    assert body["hidden_count"] >= 1


@pytest.mark.asyncio
async def test_dead_and_blocked_fold_into_failed(client, auth_headers, db):
    root_id, dead_id, _ = await _seed_tree(db)

    r = await client.get(f"/api/chats/{root_id}/hierarchy?active_only=false", headers=auth_headers)
    assert r.status_code == 200, r.text
    node = next(n for n in r.json()["nodes"] if n["id"] == dead_id)
    # failed + dead + blocked all counted as failed; node reads terminal-failed, not active.
    assert node["task_counts"]["failed"] == 3
    assert node["status"] == "failed"
