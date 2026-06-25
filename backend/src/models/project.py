import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # github, gitlab
    provider_chain_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("provider_chains.id"), nullable=True)
    pm_agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    tools: Mapped[list] = mapped_column(JSON, default=list)
    mcps: Mapped[list] = mapped_column(JSON, default=list)
    env_vars: Mapped[dict] = mapped_column(JSON, default=dict)  # {KEY: encrypted VALUE}
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    @property
    def plain_env_vars(self) -> dict:
        from src.core.security import decrypt_env_map
        return decrypt_env_map(self.env_vars)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    org: Mapped["Organization"] = relationship("Organization", back_populates="projects")  # noqa: F821
    pm_agent: Mapped["Agent | None"] = relationship("Agent", back_populates="projects")  # noqa: F821
    provider_chain: Mapped["ProviderChain | None"] = relationship("ProviderChain", lazy="joined")  # noqa: F821
    chats: Mapped[list["Chat"]] = relationship("Chat", back_populates="project", lazy="select")  # noqa: F821
    memories: Mapped[list["ProjectMemory"]] = relationship("ProjectMemory", back_populates="project", lazy="select", cascade="all, delete-orphan")  # noqa: F821
