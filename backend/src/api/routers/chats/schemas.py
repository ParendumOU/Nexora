from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class ChatCreate(BaseModel):
    title: str = "New Chat"
    project_id: str | None = None
    project_ids: list[str] | None = None
    parent_chat_id: str | None = None
    agent_id: str | None = None
    provider_chain_id: str | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    sync_response: bool = False
    sync_timeout: int = 10


class ChatStats(BaseModel):
    subchat_count: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    running: bool = False  # chat (or its subtree) has a live turn / active task


class ChatResponse(BaseModel):
    id: str
    title: str
    project_id: str | None
    project_ids: list[str] | None = None
    parent_chat_id: str | None
    agent_id: str | None
    agent_name: str | None = None
    provider_chain_id: str | None
    direct_provider_id: str | None = None
    is_shared: bool = False
    created_by_id: str | None = None
    created_by_name: str | None = None
    notes: str | None = None
    stats: ChatStats | None = None
    webhook_url: str | None = None
    sync_response: bool = False
    sync_timeout: int = 10

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata_: dict = {}
    provider_used: str | None
    agent_id: str | None
    agent_name: str | None
    user_id: str | None = None
    user_name: str | None = None
    excluded: bool = False
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ParticipantResponse(BaseModel):
    id: str
    full_name: str
    email: str
    avatar_url: str | None = None
    avatar_emoji: str | None = None

    model_config = {"from_attributes": True}


class ForkRequest(BaseModel):
    before_message_id: str


class ChatNoteCreate(BaseModel):
    content: str
    description: Optional[str] = None
    author: Optional[str] = None
    source_chat_id: Optional[str] = None


class ChatNoteUpdate(BaseModel):
    content: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None


class ChatNoteResponse(BaseModel):
    id: str
    chat_id: str
    content: str
    description: Optional[str] = None
    author: Optional[str] = None
    source_chat_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatNotesListResponse(BaseModel):
    chat_id: str
    notes: list[ChatNoteResponse]
    total: int
    page: int
    page_size: int
