from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

schedule_upload_batch_no_seq = Sequence(
    "schedule_upload_batch_no_seq",
    schema="schedule",
    metadata=Base.metadata,
)


class ScheduleUploadBatchModel(Base):
    __tablename__ = "schedule_upload_batches"
    __table_args__ = (
        UniqueConstraint("batch_no", name="uq_schedule_upload_batches_batch_no"),
        CheckConstraint("row_count > 0", name="ck_schedule_upload_batches_row_count"),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="ck_schedule_upload_batches_status",
        ),
        CheckConstraint(
            "(status = 'PENDING_APPROVAL') = (reviewed_by IS NULL AND reviewed_at IS NULL)",
            name="ck_schedule_upload_batches_review",
        ),
        Index("ix_schedule_upload_batches_status_submitted", "status", text("submitted_at DESC")),
        Index("ix_schedule_upload_batches_uploaded_by_submitted", "uploaded_by", text("submitted_at DESC")),
        {"schema": "schedule"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    batch_no: Mapped[str] = mapped_column(String(30), nullable=False)
    supervisor_employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PENDING_APPROVAL'")
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScheduleUploadBatchRowModel(Base):
    __tablename__ = "schedule_upload_batch_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_no", name="uq_schedule_upload_batch_rows_batch_row"),
        CheckConstraint("row_no > 0", name="ck_schedule_upload_batch_rows_row_no"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_schedule_upload_batch_rows_effective_dates",
        ),
        Index("ix_schedule_upload_batch_rows_employee", "employee_id"),
        {"schema": "schedule"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    batch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.schedule_upload_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule_code: Mapped[str] = mapped_column(String(30), nullable=False)
    assignment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    rest_day_pattern_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_schedule_assignment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.employee_schedule_assignments.id"),
        nullable=True,
    )
