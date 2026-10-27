from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmployeeLoanModel(Base):
    __tablename__ = "employee_loans"
    __table_args__ = (
        CheckConstraint("principal_amount > 0", name="ck_employee_loan_principal"),
        CheckConstraint("installment_amount > 0", name="ck_employee_loan_installment"),
        CheckConstraint("outstanding_balance >= 0", name="ck_employee_loan_balance"),
        CheckConstraint(
            "schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')",
            name="ck_employee_loan_schedule",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'RETIRED', 'PAID_OFF')",
            name="ck_employee_loan_status",
        ),
        UniqueConstraint("reference_number", name="uq_employee_loan_reference_number"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    payroll_group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.payroll_groups.id"), nullable=False
    )
    reference_number: Mapped[str] = mapped_column(String(50), nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    schedule: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    outstanding_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ACTIVE'"))
    previous_loan_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.employee_loans.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )


class EmployeeLoanRepaymentModel(Base):
    __tablename__ = "employee_loan_repayments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_employee_loan_repayment_amount"),
        UniqueConstraint("loan_id", "cutoff_id", name="uq_employee_loan_repayment_cutoff"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    loan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.employee_loans.id"), nullable=False
    )
    cutoff_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.cutoffs.id"), nullable=False
    )
    gross_pay_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.gross_pay_runs.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
