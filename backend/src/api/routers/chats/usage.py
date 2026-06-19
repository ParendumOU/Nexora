from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, Message
from src.api.routers.chats.access import _can_access_chat

router = APIRouter()


@router.post("/{chat_id}/cancel-all", status_code=200)
async def cancel_all_tasks(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel everything under this chat hierarchy.

    Stops top-level WS streams, orchestrator resume loops, sub-agent
    iterations, queued tasks, watchdog nudges, and clears stream buffers.
    Delegates to src.services.chat_cancel.cancel_chat_tree — the same helper
    used by Telegram /cancel + /stop commands.
    """
    from src.services.chat_cancel import cancel_chat_tree
    return await cancel_chat_tree(chat_id, reason="Cancelled by user")


@router.get("/{chat_id}/usage")
async def get_chat_usage(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    # BFS to collect this chat + all descendant sub-chats
    all_chat_ids: list[str] = []
    queue = [chat_id]
    visited: set[str] = set()
    while queue:
        cid = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        all_chat_ids.append(cid)
        r = await db.execute(select(Chat.id).where(Chat.parent_chat_id == cid))
        queue.extend(row[0] for row in r.all())

    msgs_result = await db.execute(
        select(Message).where(Message.chat_id.in_(all_chat_ids))
    )
    messages = msgs_result.scalars().all()

    total_input = 0
    total_output = 0
    tool_calls = 0
    by_provider: dict[str, dict] = {}
    by_tool: dict[str, list] = {}
    for msg in messages:
        meta = msg.metadata_ or {}
        tool_calls += int(meta.get("tool_call_count", 0))
        for call in meta.get("tool_calls_detail", []):
            name = call.get("name", "unknown")
            if name not in by_tool:
                by_tool[name] = []
            by_tool[name].append({"args": call.get("args", {})})
        usage = meta.get("usage", {})
        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        total_input += inp
        total_output += out
        if (inp or out) and msg.provider_used:
            p = msg.provider_used
            if p not in by_provider:
                by_provider[p] = {"input_tokens": 0, "output_tokens": 0}
            by_provider[p]["input_tokens"] += inp
            by_provider[p]["output_tokens"] += out

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "tool_calls": tool_calls,
        "by_provider": [{"provider": k, **v} for k, v in by_provider.items()],
        "by_tool": [{"name": k, "count": len(v), "calls": v} for k, v in sorted(by_tool.items(), key=lambda x: -len(x[1]))],
    }
