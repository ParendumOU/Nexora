import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class InstalledPackage(Base):
    """Provenance for a marketplace item installed into an org.

    Records WHERE an installed skill/tool/persona/agent came from (marketplace
    origin + slug) and at WHAT version, so the update-checker can compare against
    the marketplace's current version and surface available updates. Independent
    of licensing — works for OSS and Cloud alike; `pricing_type` only flags which
    items need an entitlement re-check before update (Cloud/paid).
    """

    __tablename__ = "installed_packages"
    __table_args__ = (
        UniqueConstraint("org_id", "item_type", "source_slug", name="uq_installed_pkg_org_type_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # skill|tool|persona|agent
    source_slug: Mapped[str] = mapped_column(String(150), nullable=False)
    origin: Mapped[str] = mapped_column(String(500), nullable=False)  # marketplace origin (scheme+host)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    installed_version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    # Latest version seen on the marketplace (set by the update-checker). NULL = not yet checked.
    available_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pricing_type: Mapped[str] = mapped_column(String(20), default="free", nullable=False)

    # Marketplace liability signal recorded at install time (GitLab #158). The
    # marketplace's coarse trust tier ("new"|"low"|"established"|"trusted") and
    # warning level ("standard"|"elevated"|"high") as fetched when installed.
    # Absent/older marketplaces default to the safe "established"/"standard".
    trust_tier: Mapped[str] = mapped_column(String(20), default="established", nullable=False)
    warning_level: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    # True when the user explicitly acknowledged the risk of a non-standard
    # (elevated/high) package on install. Always False for standard installs.
    risk_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
