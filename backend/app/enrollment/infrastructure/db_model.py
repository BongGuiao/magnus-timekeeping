from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy.dialects.postgresql import UUID as PGUUID


from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.enrollment.domain.entities.enrollment import EnrollmentStatus


class FaceEnrollmentModel(Base):
    __tablename__ = "face_enrollment_data"
    __table_args__ = {"schema": "biometric"}
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("hr.employees.id", ondelete="CASCADE"), index=True, nullable=False)
    face_encoding: Mapped[Optional[list[float]]] = mapped_column(ARRAY(Float), nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus, native_enum=False),
        default=EnrollmentStatus.PENDING,
        nullable=False,
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FaceEnrollmentResetModel(Base):
    __tablename__ = "face_enrollment_resets"
    __table_args__ = (
        CheckConstraint(
            "sample_count > 0 AND cardinality(sample_ids) = sample_count",
            name="ck_face_enrollment_resets_samples",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_face_enrollment_resets_reason"),
        Index("ix_face_enrollment_resets_employee_time", "employee_id", "reset_at"),
        {"schema": "biometric"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # Snapshot identifiers deliberately survive employee/account deletion.
    employee_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    employee_no: Mapped[str] = mapped_column(String(30), nullable=False)
    reset_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sample_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    profile_photo_cleared: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
