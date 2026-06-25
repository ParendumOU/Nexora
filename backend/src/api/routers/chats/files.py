"""File upload/download endpoints for chat attachment trees."""
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user as current_user, get_db
from src.api.routers.chats.access import _can_access_chat
from src.core.config import get_settings
from src.models.chat import Chat
from src.models.chat_file import ChatFile
from src.models.user import User

router = APIRouter()


async def _get_root_chat_id(chat_id: str, db: AsyncSession) -> str:
    visited: set[str] = set()
    cur_id = chat_id
    while cur_id and cur_id not in visited:
        visited.add(cur_id)
        r = await db.execute(select(Chat).where(Chat.id == cur_id))
        chat = r.scalar_one_or_none()
        if not chat or not chat.parent_chat_id:
            return cur_id
        cur_id = chat.parent_chat_id
    return chat_id


async def _load_chat(chat_id: str, db: AsyncSession) -> Chat:
    r = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = r.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.post("/{chat_id}/files")
async def upload_files(
    chat_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    settings = get_settings()
    chat = await _load_chat(chat_id, db)
    if not await _can_access_chat(user.id, chat, db):
        raise HTTPException(status_code=403, detail="Forbidden")

    root_chat_id = await _get_root_chat_id(chat_id, db)
    upload_root = Path(settings.upload_dir) / root_chat_id
    upload_root.mkdir(parents=True, exist_ok=True)

    results = []
    for upload in files:
        original_name = upload.filename or "file"
        ext = Path(original_name).suffix
        stored_name = f"{uuid.uuid4()}{ext}"
        dest = upload_root / stored_name

        content = await upload.read()
        limit = settings.max_upload_size_mb * 1024 * 1024
        if len(content) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"{original_name} exceeds {settings.max_upload_size_mb}MB limit",
            )

        dest.write_bytes(content)

        guessed_ct = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        chat_file = ChatFile(
            chat_id=chat_id,
            root_chat_id=root_chat_id,
            user_id=user.id,
            original_filename=original_name,
            stored_filename=stored_name,
            content_type=upload.content_type or guessed_ct,
            size_bytes=len(content),
        )
        db.add(chat_file)
        await db.flush()
        results.append({
            "id": chat_file.id,
            "name": chat_file.original_filename,
            "size": chat_file.size_bytes,
            "content_type": chat_file.content_type,
            "chat_id": chat_id,
            "created_at": chat_file.created_at.isoformat(),
        })

    await db.commit()
    return results


@router.get("/{chat_id}/files")
async def list_files(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    chat = await _load_chat(chat_id, db)
    if not await _can_access_chat(user.id, chat, db):
        raise HTTPException(status_code=403, detail="Forbidden")

    root_chat_id = await _get_root_chat_id(chat_id, db)
    r = await db.execute(
        select(ChatFile)
        .where(ChatFile.root_chat_id == root_chat_id)
        .order_by(ChatFile.created_at.desc())
    )
    files = r.scalars().all()
    return [
        {
            "id": f.id,
            "name": f.original_filename,
            "folder": getattr(f, "folder", "") or "",
            "size": f.size_bytes,
            "content_type": f.content_type,
            "chat_id": f.chat_id,
            "created_at": f.created_at.isoformat(),
        }
        for f in files
    ]


@router.delete("/{chat_id}/files/{file_id}", status_code=204)
async def delete_file(
    chat_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    chat = await _load_chat(chat_id, db)
    if not await _can_access_chat(user.id, chat, db):
        raise HTTPException(status_code=403, detail="Forbidden")

    r = await db.execute(select(ChatFile).where(ChatFile.id == file_id))
    file_obj = r.scalar_one_or_none()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")
    if file_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not file owner")

    settings = get_settings()
    path = Path(settings.upload_dir) / file_obj.root_chat_id / file_obj.stored_filename
    if path.exists():
        path.unlink(missing_ok=True)

    await db.delete(file_obj)
    await db.commit()


@router.get("/{chat_id}/files/{file_id}/content")
async def get_file_content(
    chat_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    chat = await _load_chat(chat_id, db)
    if not await _can_access_chat(user.id, chat, db):
        raise HTTPException(status_code=403, detail="Forbidden")

    r = await db.execute(select(ChatFile).where(ChatFile.id == file_id))
    file_obj = r.scalar_one_or_none()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")

    settings = get_settings()
    path = Path(settings.upload_dir) / file_obj.root_chat_id / file_obj.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File data not found on server")

    return FileResponse(
        path=str(path),
        media_type=file_obj.content_type,
        filename=file_obj.original_filename,
    )
