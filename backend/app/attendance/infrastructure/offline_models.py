from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OfflinePermitModel(Base):
    __tablename__ = "offline_permits"
    __table_args__ = {"schema": "attendance"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), index=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("identity.devices.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(JSONB)


class OfflinePunchEventModel(Base):
    __tablename__ = "offline_punch_events"
    __table_args__ = (
        UniqueConstraint("permit_id", "sequence", name="uq_offline_event_sequence"),
        CheckConstraint("status IN ('ACCEPTED', 'NEEDS_REVIEW', 'REJECTED')", name="ck_offline_event_status"),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    permit_id: Mapped[UUID] = mapped_column(ForeignKey("attendance.offline_permits.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), index=True)
    sequence: Mapped[int]
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    signature: Mapped[str] = mapped_column(String(86))
    status: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attendance_id: Mapped[UUID | None] = mapped_column(ForeignKey("attendance.attendance_records.id"), nullable=True)
    encrypted_photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("identity.users.id"), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
