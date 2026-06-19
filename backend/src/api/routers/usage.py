from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, Message

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/summary")
async def get_usage_summary(
    period_days: int = Query(30, ge=7, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=period_days)

    chat_result = await db.execute(
        select(Chat.id).where(Chat.user_id == current_user.id)
    )
    chat_ids = [r[0] for r in chat_result.all()]

    if not chat_ids:
        return {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tool_calls": 0,
            "by_provider": [],
            "by_day": [],
        }

    msg_result = await db.execute(
        select(Message).where(
            Message.chat_id.in_(chat_ids),
            Message.created_at >= since,
        )
    )
    messages = msg_result.scalars().all()

    total_input = 0
    total_output = 0
    total_tool_calls = 0
    by_provider: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_day: dict[str, dict] = {}

    for msg in messages:
        meta = msg.metadata_ or {}
        total_tool_calls += int(meta.get("tool_call_count", 0))
        usage = meta.get("usage", {})
        inp = int(usage.get("input_tokens", 0) or 0)
        out = int(usage.get("output_tokens", 0) or 0)
        total_input += inp
        total_output += out

        if inp or out:
            provider = msg.provider_used or "unknown"
            if provider not in by_provider:
                by_provider[provider] = {"input_tokens": 0, "output_tokens": 0}
            by_provider[provider]["input_tokens"] += inp
            by_provider[provider]["output_tokens"] += out

            model = meta.get("model") or "unknown"
            if model not in by_model:
                by_model[model] = {"input_tokens": 0, "output_tokens": 0}
            by_model[model]["input_tokens"] += inp
            by_model[model]["output_tokens"] += out

            if msg.created_at:
                day = msg.created_at.strftime("%Y-%m-%d")
                if day not in by_day:
                    by_day[day] = {"date": day, "input_tokens": 0, "output_tokens": 0}
                by_day[day]["input_tokens"] += inp
                by_day[day]["output_tokens"] += out

    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tool_calls": total_tool_calls,
        "by_provider": [{"provider": k, **v} for k, v in by_provider.items()],
        "by_model": [{"model": k, **v} for k, v in by_model.items()],
        "by_day": sorted(by_day.values(), key=lambda x: x["date"]),
    }
