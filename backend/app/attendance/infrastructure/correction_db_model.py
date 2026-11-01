from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AttendanceCorrectionModel(Base):
    __tablename__ = "correction_requests"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_corrections_status"),
        CheckConstraint("requested_clock_out_at > requested_clock_in_at", name="ck_corrections_period"),
        Index(
            "uq_corrections_pending_employee_date", "employee_id", "work_date", unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr.employees.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id"), nullable=False)
    attendance_record_id: Mapped[UUID | None] = mapped_column(ForeignKey("attendance.attendance_records.id"))
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    original_clock_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_clock_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_reference: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'PENDING'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("identity.users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
