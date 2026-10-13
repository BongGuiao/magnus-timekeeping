from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LeaveTypeModel(Base):
    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "leave_code",
            "effective_from",
            name="uq_leave_types_company_code_effective_from",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_leave_types_effective_dates",
        ),
        {"schema": "leave_mgmt"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.companies.id"),
        nullable=False,
    )
    leave_code: Mapped[str] = mapped_column(String(30), nullable=False)
    leave_name: Mapped[str] = mapped_column(String(150), nullable=False)
    leave_category: Mapped[str] = mapped_column(String(30), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    annual_entitlement_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    accrual_method: Mapped[str] = mapped_column(String(30), nullable=False)
    minimum_service_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    allow_negative_balance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    maximum_negative_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    carryover_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    maximum_carryover_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expiry_rule: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'NONE'"))
    cash_conversion_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    advance_notice_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    document_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_trigger_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    exclude_rest_days: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    exclude_holidays: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ACTIVE'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
