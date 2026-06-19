import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text, JSON, Float, Boolean, Integer, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), default="custom")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    soul: Mapped[dict] = mapped_column(JSON, default=dict)          # personality, expertise, etc.
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)        # list of skill names
    mcps: Mapped[list] = mapped_column(JSON, default=list)          # [{server_id?, name, url, allowed_tools?}]
    tools: Mapped[list] = mapped_column(JSON, default=list)         # list of tool names
    env_vars: Mapped[dict] = mapped_column(JSON, default=dict)      # {KEY: VALUE}
    max_subagents: Mapped[int] = mapped_column(Integer, default=5)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=2)
    model_pref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    max_tokens: Mapped[int] = mapped_column(Integer, default=8192)
    flow_config: Mapped[dict] = mapped_column(JSON, default=dict)   # React Flow positions
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    share_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    org: Mapped["Organization"] = relationship("Organization", back_populates="agents")  # noqa: F821
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="pm_agent", lazy="select")  # noqa: F821
    memories: Mapped[list["AgentMemory"]] = relationship("AgentMemory", back_populates="agent", lazy="select", cascade="all, delete-orphan")  # noqa: F821
    versions: Mapped[list["AgentVersion"]] = relationship("AgentVersion", back_populates="agent", lazy="select", cascade="all, delete-orphan", order_by="AgentVersion.version_number")  # noqa: F821
