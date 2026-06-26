"""GET/POST /chats/{id}/flags — regression for the swapped-args bug.

get_chat_flags/set_chat_flags called _can_access_chat(chat_id, current_user, db) but the
helper is _can_access_chat(user_id, chat, db). Passing a User where a Chat was expected
made every call AttributeError -> 500, so the UI's per-chat toggle restore broke on every
chat open.
"""
import uuid
import pytest
from sqlalchemy import select


async def _make_chat(db, email="fixture@example.com"):
    from src.models.user import User
    from src.models.chat import Chat
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    chat = Chat(id=str(uuid.uuid4()), user_id=user.id, title="c")
    db.add(chat)
    await db.commit()
    return chat.id


@pytest.mark.asyncio
async def test_get_chat_flags_ok_for_owner(client, auth_headers, db):
    chat_id = await _make_chat(db)
    r = await client.get(f"/api/chats/{chat_id}/flags", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["yolo"] is False and body["autopilot"] is False


@pytest.mark.asyncio
async def test_get_chat_flags_404_for_unknown(client, auth_headers):
    r = await client.get(
        "/api/chats/00000000-0000-0000-0000-000000000000/flags", headers=auth_headers
    )
    assert r.status_code == 404
