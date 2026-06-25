import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    integration_type: Mapped[str] = mapped_column(String(50), nullable=False)  # telegram, github, gitlab
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)     # Fernet-encrypted JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def get_config(self) -> dict:
        """Decrypt + parse the config JSON (tolerates legacy plaintext rows)."""
        import json
        from src.core.security import decrypt_safe
        raw = decrypt_safe(self.config)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def set_config(self, data: dict) -> None:
        """Serialize + encrypt the config JSON (holds bot_token/api_key secrets)."""
        import json
        from src.core.security import encrypt
        self.config = encrypt(json.dumps(data)) if data else None
