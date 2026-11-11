from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KioskDeviceModel(Base):
    __tablename__ = "kiosk_devices"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REVOKED')", name="ck_kiosk_status"),
        CheckConstraint(
            "status != 'APPROVED' OR (company_id IS NOT NULL AND location_id IS NOT NULL)",
            name="ck_kiosk_approved_scope",
        ),
        ForeignKeyConstraint(
            ["company_id", "location_id"], ["core.locations.company_id", "core.locations.id"],
            name="fk_kiosk_location_company",
        ),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    device_name: Mapped[str] = mapped_column(String(100))
    public_key_jwk: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    pairing_code: Mapped[str] = mapped_column(String(32), unique=True)
    pairing_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.companies.id"), nullable=True,
    )
    location_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KioskChallengeModel(Base):
    __tablename__ = "kiosk_challenges"
    __table_args__ = (
        CheckConstraint("purpose IN ('STATUS', 'IDENTIFY', 'CLOCK', 'BREAK')", name="ck_kiosk_challenge_purpose"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    device_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.kiosk_devices.id", ondelete="CASCADE"), index=True,
    )
    purpose: Mapped[str] = mapped_column(String(10))
    payload_hash: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
