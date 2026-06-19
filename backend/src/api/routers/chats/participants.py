import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.database import get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat, ChatParticipant
from src.models.project import Project
from src.models.org import OrgMember
from src.api.routers.chats.access import _can_access_chat
from src.api.routers.chats.schemas import ParticipantResponse

router = APIRouter()


@router.get("/{chat_id}/participants", response_model=list[ParticipantResponse])
async def get_participants(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    if chat.project_id:
        proj_result = await db.execute(select(Project).where(Project.id == chat.project_id))
        project = proj_result.unique().scalar_one_or_none()
        if project:
            members_result = await db.execute(
                select(User)
                .join(OrgMember, OrgMember.user_id == User.id)
                .where(OrgMember.org_id == project.org_id)
            )
            return members_result.scalars().all()

    owner_result = await db.execute(select(User).where(User.id == chat.user_id))
    owner = owner_result.scalar_one_or_none()
    return [owner] if owner else []


@router.post("/{chat_id}/join", status_code=200)
async def join_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    existing = await db.execute(
        select(ChatParticipant).where(
            ChatParticipant.chat_id == chat_id,
            ChatParticipant.user_id == current_user.id,
        )
    )
    if not existing.scalar_one_or_none():
        db.add(ChatParticipant(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_id=current_user.id,
            role="participant",
        ))
        await db.commit()

    return {"status": "joined"}
