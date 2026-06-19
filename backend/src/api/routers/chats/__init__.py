from fastapi import APIRouter
from src.api.routers.chats import search, crud, messages, participants, hierarchy, usage, files, stream, execution_tree

router = APIRouter(prefix="/chats", tags=["chats"])

# search MUST be registered before crud to avoid /{chat_id} swallowing /search
router.include_router(search.router)
router.include_router(crud.router)
router.include_router(messages.router)
router.include_router(participants.router)
router.include_router(hierarchy.router)
router.include_router(usage.router)
router.include_router(files.router)
router.include_router(stream.router)
router.include_router(execution_tree.router)
