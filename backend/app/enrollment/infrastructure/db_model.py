from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy.dialects.postgresql import UUID as PGUUID


from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, String, func, text
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
