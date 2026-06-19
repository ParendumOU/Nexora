import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class GitCredential(Base):
    __tablename__ = "git_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)   # "github" | "gitlab"
    token: Mapped[str] = mapped_column(String(1000), nullable=False)    # Fernet-encrypted PAT
    color: Mapped[str] = mapped_column(String(20), default="#6366f1")   # display color
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # self-hosted GitLab
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def plain_token(self) -> str:
        """Return the decrypted personal access token.

        Handles both Fernet-encrypted tokens (post-migration) and legacy
        plain-text tokens stored before encryption was introduced.
        """
        from src.core.security import decrypt
        try:
            return decrypt(self.token)
        except Exception:
            return self.token
