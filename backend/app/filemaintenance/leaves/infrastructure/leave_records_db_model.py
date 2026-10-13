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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmployeeEntitlementModel(Base):
    __tablename__ = "employee_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "leave_type_id",
            "entitlement_year",
            name="uq_employee_entitlements_employee_type_year",
        ),
        {"schema": "leave_mgmt"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leave_mgmt.leave_types.id"), nullable=False
    )
    entitlement_year: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    granted_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    accrued_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    carryover_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    adjustment_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    used_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reserved_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expired_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    converted_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    available_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeaveApplicationModel(Base):
    __tablename__ = "leave_applications"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_leave_applications_end_after_start"),
        {"schema": "leave_mgmt"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    application_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leave_mgmt.leave_types.id"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unpaid_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    contact_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    reliever_employee_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=True
    )
    is_retroactive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # These references are enforced in the database; workflow/schedule models are not registered in this ORM.
    workflow_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payroll_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class LeaveApplicationDateModel(Base):
    __tablename__ = "leave_application_dates"
    __table_args__ = (
        UniqueConstraint(
            "leave_application_id",
            "leave_date",
            name="uq_leave_application_dates_application_date",
        ),
        {"schema": "leave_mgmt"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    leave_application_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("leave_mgmt.leave_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    leave_date: Mapped[date] = mapped_column(Date, nullable=False)
    # The database FK to schedule.daily_rosters is retained in the existing table.
    roster_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    requested_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_paid_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    approved_unpaid_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    holiday_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rest_day_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    attendance_overlap_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    final_charge_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class LeaveLedgerModel(Base):
    __tablename__ = "leave_ledger"
    __table_args__ = {"schema": "leave_mgmt"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leave_mgmt.leave_types.id"), nullable=False
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    minutes_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    posted_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
