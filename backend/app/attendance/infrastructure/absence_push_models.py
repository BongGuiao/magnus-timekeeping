from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MobilePushDeviceModel(Base):
    __tablename__ = "mobile_push_devices"
    __table_args__ = {"schema": "identity"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    session_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AbsencePushDeliveryModel(Base):
    __tablename__ = "absence_push_deliveries"
    __table_args__ = (
        UniqueConstraint("alert_id", "user_id", "device_id", name="uq_absence_push_recipient_device"),
        Index("ix_absence_push_due", "state", "next_attempt_at"),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    alert_id: Mapped[UUID] = mapped_column(ForeignKey("attendance.absence_streak_alerts.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), nullable=False)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("identity.mobile_push_devices.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    receipt_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
