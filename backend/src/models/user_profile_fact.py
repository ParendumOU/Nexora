import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class UserProfileFact(Base):
    """A single keyed fact about a user (e.g. role -> 'DevOps engineer').

    Stored as discrete (key, value) rows so the `remember_user` tool can patch
    one fact without clobbering the rest of the profile (the old single-blob
    `User.notes` overwrite bug). The freeform legacy notes survive as the
    reserved key ``freeform``.
    """

    __tablename__ = "user_profile_facts"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_profile_fact_user_key"),
        Index("ix_user_profile_facts_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)  # agent name or 'manual'/'legacy'

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
