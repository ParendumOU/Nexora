import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class TelegramPending(Base):
    __tablename__ = "telegram_pending"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    integration_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tg_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    tg_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tg_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
