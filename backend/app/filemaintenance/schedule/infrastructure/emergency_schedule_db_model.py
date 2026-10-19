from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmergencyScheduleRequestModel(Base):
    __tablename__ = "emergency_schedule_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')",
            name="ck_emergency_schedule_requests_status",
        ),
        CheckConstraint(
            "(status = 'PENDING_APPROVAL') = (reviewed_by IS NULL AND reviewed_at IS NULL)",
            name="ck_emergency_schedule_requests_review",
        ),
        Index(
            "uq_emergency_schedule_requests_active_day",
            "employee_id",
            "work_date",
            unique=True,
            postgresql_where=text("status IN ('PENDING_APPROVAL', 'APPROVED')"),
        ),
        Index(
            "ix_emergency_schedule_requests_pending_date",
            "status",
            "work_date",
        ),
        {"schema": "schedule"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    schedule_template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("schedule.schedule_templates.id"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PENDING_APPROVAL'")
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
