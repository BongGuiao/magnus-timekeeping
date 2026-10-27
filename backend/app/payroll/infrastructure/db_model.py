from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmployeeCompensationModel(Base):
    __tablename__ = "employee_compensations"
    __table_args__ = (
        CheckConstraint("base_rate > 0", name="ck_employee_compensations_base_rate"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employee_compensations_effective_dates",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_employee_compensations_currency",
        ),
        Index(
            "ix_employee_compensations_employee_group_period",
            "employee_id",
            "payroll_group_id",
            "effective_from",
            "effective_to",
        ),
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
    base_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'PHP'"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PayrollEarningRuleModel(Base):
    __tablename__ = "earning_rules"
    __table_args__ = (
        CheckConstraint(
            "component_code IN ("
            "'REGULAR', 'PAID_LEAVE', 'OFFICIAL_BUSINESS', 'REST_DAY', 'SPECIAL_DAY', "
            "'HOLIDAY', 'ORDINARY_OT', 'REST_DAY_OT', 'SPECIAL_DAY_OT', 'HOLIDAY_OT', "
            "'NIGHT_REGULAR', 'NIGHT_OT')",
            name="ck_payroll_earning_rules_component",
        ),
        CheckConstraint("multiplier >= 0", name="ck_payroll_earning_rules_multiplier"),
        UniqueConstraint(
            "payroll_group_id", "component_code", name="uq_payroll_earning_rules_group_component"
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    payroll_group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.payroll_groups.id"), nullable=False
    )
    component_code: Mapped[str] = mapped_column(String(30), nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BenefitTypeModel(Base):
    __tablename__ = "benefit_types"
    __table_args__ = (
        CheckConstraint(
            "category IN ('CASH_ALLOWANCE', 'ONE_TIME_BONUS', 'REIMBURSEMENT', "
            "'EMPLOYER_PAID_INSURANCE', 'NON_CASH', 'EMPLOYEE_DEDUCTION')",
            name="ck_payroll_benefit_type_category",
        ),
        CheckConstraint(
            "tax_treatment IN ('TAXABLE', 'EXEMPT', 'EXEMPT_LIMITED')",
            name="ck_payroll_benefit_type_tax_treatment",
        ),
        CheckConstraint(
            "posting_schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')",
            name="ck_payroll_benefit_type_posting_schedule",
        ),
        CheckConstraint(
            "withholding_timing = 'PAY_PERIOD' OR "
            "(withholding_timing = 'YEAR_END' AND category = 'ONE_TIME_BONUS' "
            "AND tax_treatment = 'TAXABLE')",
            name="ck_payroll_benefit_type_withholding_timing",
        ),
        CheckConstraint(
            "category != 'EMPLOYEE_DEDUCTION' OR tax_treatment = 'EXEMPT'",
            name="ck_payroll_benefit_deduction_tax_treatment",
        ),
        CheckConstraint(
            "category != 'EMPLOYEE_DEDUCTION' OR attendance_based = false",
            name="ck_payroll_benefit_deduction_not_attendance_based",
        ),
        CheckConstraint(
            "attendance_based OR (deduct_for_late = false AND deduct_for_undertime = false)",
            name="ck_payroll_benefit_time_deductions_require_attendance",
        ),
        UniqueConstraint("payroll_group_id", "code", name="uq_payroll_benefit_type_group_code"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    payroll_group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.payroll_groups.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(20), nullable=False)
    withholding_timing: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PAY_PERIOD'")
    )
    attendance_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deduct_for_late: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deduct_for_undertime: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    posting_schedule: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'EVERY_CUTOFF'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class CutoffBenefitModel(Base):
    __tablename__ = "cutoff_benefits"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payroll_cutoff_benefit_amount"),
        CheckConstraint(
            "withholding_timing = 'PAY_PERIOD' OR "
            "(withholding_timing = 'YEAR_END' AND category = 'ONE_TIME_BONUS' "
            "AND tax_treatment = 'TAXABLE')",
            name="ck_payroll_cutoff_benefit_withholding_timing",
        ),
        CheckConstraint(
            "category != 'EMPLOYEE_DEDUCTION' OR attendance_based = false",
            name="ck_payroll_cutoff_benefit_deduction_not_attendance_based",
        ),
        CheckConstraint(
            "attendance_based OR (deduct_for_late = false AND deduct_for_undertime = false)",
            name="ck_payroll_cutoff_benefit_time_deductions_require_attendance",
        ),
        UniqueConstraint(
            "cutoff_id",
            "employee_id",
            "benefit_type_id",
            name="uq_payroll_cutoff_benefit_employee_type",
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    cutoff_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.cutoffs.id"), nullable=False
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    benefit_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.benefit_types.id"), nullable=False
    )
    benefit_code: Mapped[str] = mapped_column(String(30), nullable=False)
    benefit_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(20), nullable=False)
    withholding_timing: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PAY_PERIOD'")
    )
    attendance_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deduct_for_late: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deduct_for_undertime: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class EmployeeBenefitDeductionModel(Base):
    __tablename__ = "employee_benefit_deductions"
    __table_args__ = (
        CheckConstraint("amount_per_occurrence > 0", name="ck_employee_benefit_deduction_amount"),
        CheckConstraint(
            "schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')",
            name="ck_employee_benefit_deduction_schedule",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employee_benefit_deduction_effective_dates",
        ),
        UniqueConstraint(
            "employee_id",
            "benefit_type_id",
            name="uq_employee_benefit_deduction_employee_type",
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    benefit_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.benefit_types.id"), nullable=False
    )
    amount_per_occurrence: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    schedule: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class EmployeeBenefitEntitlementModel(Base):
    __tablename__ = "employee_benefit_entitlements"
    __table_args__ = (
        CheckConstraint(
            "amount_per_occurrence > 0",
            name="ck_employee_benefit_entitlement_amount",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employee_benefit_entitlement_effective_dates",
        ),
        CheckConstraint(
            "schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')",
            name="ck_employee_benefit_entitlement_schedule",
        ),
        UniqueConstraint(
            "employee_id",
            "benefit_type_id",
            name="uq_employee_benefit_entitlement_employee_type",
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    benefit_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.benefit_types.id"), nullable=False
    )
    amount_per_occurrence: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    schedule: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'EVERY_CUTOFF'")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class StatutoryContributionScheduleModel(Base):
    __tablename__ = "statutory_contribution_schedules"
    __table_args__ = (
        CheckConstraint(
            "program_code IN ('SSS', 'PHILHEALTH', 'PAGIBIG')",
            name="ck_payroll_statutory_contribution_program",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name="ck_payroll_statutory_contribution_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_payroll_statutory_contribution_dates",
        ),
        UniqueConstraint(
            "program_code",
            "effective_from",
            name="uq_payroll_statutory_contribution_period",
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    program_code: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'DRAFT'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class StatutoryContributionBracketModel(Base):
    __tablename__ = "statutory_contribution_brackets"
    __table_args__ = (
        CheckConstraint("bracket_number > 0", name="ck_payroll_contribution_bracket_number"),
        CheckConstraint("compensation_min >= 0", name="ck_payroll_contribution_min"),
        CheckConstraint(
            "compensation_max IS NULL OR compensation_max >= compensation_min",
            name="ck_payroll_contribution_max",
        ),
        CheckConstraint("contribution_base >= 0", name="ck_payroll_contribution_base"),
        CheckConstraint(
            "employee_rate >= 0 AND employee_rate <= 1",
            name="ck_payroll_contribution_employee_rate",
        ),
        CheckConstraint(
            "employer_rate >= 0 AND employer_rate <= 1",
            name="ck_payroll_contribution_employer_rate",
        ),
        CheckConstraint(
            "employee_fixed_amount >= 0 AND employer_fixed_amount >= 0 "
            "AND employer_additional_fixed_amount >= 0",
            name="ck_payroll_contribution_fixed_amounts",
        ),
        CheckConstraint(
            "(employee_contribution_cap IS NULL OR employee_contribution_cap >= 0) "
            "AND (employer_contribution_cap IS NULL OR employer_contribution_cap >= 0)",
            name="ck_payroll_contribution_caps",
        ),
        UniqueConstraint(
            "schedule_id", "bracket_number", name="uq_payroll_contribution_bracket_number"
        ),
        UniqueConstraint(
            "schedule_id", "compensation_min", name="uq_payroll_contribution_bracket_min"
        ),
        Index(
            "uq_payroll_contribution_bracket_open_ended",
            "schedule_id",
            unique=True,
            postgresql_where=text("compensation_max IS NULL"),
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    schedule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.statutory_contribution_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    bracket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    compensation_min: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    compensation_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    contribution_base: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    employee_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False, server_default=text("0")
    )
    employer_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False, server_default=text("0")
    )
    employee_fixed_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    employer_fixed_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    employer_additional_fixed_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    employee_contribution_cap: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    employer_contribution_cap: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )


class WithholdingTaxScheduleModel(Base):
    __tablename__ = "withholding_tax_schedules"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name="ck_payroll_withholding_tax_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_payroll_withholding_tax_dates",
        ),
        CheckConstraint(
            "tax_exempt_benefit_limit >= 0",
            name="ck_payroll_tax_exempt_benefit_limit",
        ),
        CheckConstraint(
            "calculation_basis IN ('ANNUAL_YTD', 'SEMI_MONTHLY')",
            name="ck_payroll_withholding_tax_calculation_basis",
        ),
        UniqueConstraint("effective_from", name="uq_payroll_withholding_tax_period"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    schedule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_exempt_benefit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    calculation_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'SEMI_MONTHLY'")
    )
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'DRAFT'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class WithholdingTaxBracketModel(Base):
    __tablename__ = "withholding_tax_brackets"
    __table_args__ = (
        CheckConstraint("bracket_number > 0", name="ck_payroll_tax_bracket_number"),
        CheckConstraint("annual_income_min >= 0", name="ck_payroll_tax_bracket_min"),
        CheckConstraint(
            "annual_income_max IS NULL OR annual_income_max >= annual_income_min",
            name="ck_payroll_tax_bracket_max",
        ),
        CheckConstraint("base_tax >= 0", name="ck_payroll_tax_bracket_base_tax"),
        CheckConstraint(
            "marginal_rate >= 0 AND marginal_rate <= 1",
            name="ck_payroll_tax_bracket_marginal_rate",
        ),
        CheckConstraint("excess_over >= 0", name="ck_payroll_tax_bracket_excess_over"),
        UniqueConstraint(
            "schedule_id", "bracket_number", name="uq_payroll_tax_bracket_number"
        ),
        UniqueConstraint(
            "schedule_id", "annual_income_min", name="uq_payroll_tax_bracket_min"
        ),
        Index(
            "uq_payroll_tax_bracket_open_ended",
            "schedule_id",
            unique=True,
            postgresql_where=text("annual_income_max IS NULL"),
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    schedule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.withholding_tax_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    bracket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_income_min: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    annual_income_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    base_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    marginal_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    excess_over: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class GrossPayRunModel(Base):
    __tablename__ = "gross_pay_runs"
    __table_args__ = (
        Index(
            "uq_payroll_gross_pay_runs_current_cutoff",
            "cutoff_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    cutoff_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.cutoffs.id"), nullable=False
    )
    calculation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GrossPayResultModel(Base):
    __tablename__ = "gross_pay_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('HOLD', 'READY')",
            name="ck_payroll_gross_pay_results_status",
        ),
        CheckConstraint(
            "gross_amount IS NULL OR gross_amount >= 0",
            name="ck_payroll_gross_pay_results_amount",
        ),
        UniqueConstraint("run_id", "employee_id", name="uq_payroll_gross_pay_results_run_employee"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.gross_pay_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    cutoff_result_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.employee_cutoff_results.id"), nullable=False
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    base_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    gross_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cash_benefit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    non_cash_benefit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    employee_benefit_deductions: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    exempt_limited_benefit_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    taxable_income: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    employee_contributions: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    employer_contributions: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    withholding_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    earning_lines: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    benefit_lines: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    contribution_lines: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    source_minutes: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollOpeningYtdBalanceModel(Base):
    __tablename__ = "opening_ytd_balances"
    __table_args__ = (
        CheckConstraint("tax_year BETWEEN 1900 AND 9999", name="ck_payroll_ytd_balance_tax_year"),
        CheckConstraint(
            "taxable_income >= 0 AND tax_withheld >= 0 AND exempt_limited_benefits >= 0",
            name="ck_payroll_ytd_balance_nonnegative",
        ),
        UniqueConstraint("previous_balance_id", name="uq_payroll_ytd_balance_predecessor"),
        Index(
            "ix_payroll_ytd_balance_employee_year_created",
            "employee_id",
            "tax_year",
            "created_at",
        ),
        Index(
            "uq_payroll_ytd_balance_root",
            "employee_id",
            "tax_year",
            unique=True,
            postgresql_where=text("previous_balance_id IS NULL"),
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    taxable_income: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_withheld: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    exempt_limited_benefits: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    previous_balance_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.opening_ytd_balances.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )


class PayrollSystemParametersModel(Base):
    __tablename__ = "company_system_parameters"
    __table_args__ = (
        CheckConstraint(
            "statutory_contribution_timing IN ('PER_CUTOFF', 'FINAL_CUTOFF')",
            name="ck_payroll_company_system_parameters_contribution_timing",
        ),
        {"schema": "payroll"},
    )

    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.companies.id"), primary_key=True
    )
    year_end_wtax_reconciliation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    thirteenth_month_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    schedule_assignment_approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    statutory_contribution_timing: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PER_CUTOFF'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )


class ThirteenthMonthRunModel(Base):
    __tablename__ = "thirteenth_month_runs"
    __table_args__ = (
        CheckConstraint("tax_year BETWEEN 1900 AND 9999", name="ck_payroll_thirteenth_month_year"),
        Index(
            "uq_payroll_thirteenth_month_current_year",
            "company_id",
            "tax_year",
            unique=True,
            postgresql_where=text("is_current AND company_id IS NOT NULL"),
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.companies.id"), nullable=True
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    covered_period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    covered_period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ThirteenthMonthResultModel(Base):
    __tablename__ = "thirteenth_month_results"
    __table_args__ = (
        CheckConstraint(
            "basic_salary_earned >= 0 AND thirteenth_month_pay >= 0 "
            "AND tax_exempt_amount >= 0 AND taxable_amount >= 0 "
            "AND source_payroll_periods >= 0",
            name="ck_payroll_thirteenth_month_result_amounts",
        ),
        UniqueConstraint(
            "run_id", "employee_id", name="uq_payroll_thirteenth_month_result_employee"
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.thirteenth_month_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    employee_no: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(240), nullable=False)
    basic_salary_earned: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    thirteenth_month_pay: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_exempt_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_payroll_periods: Mapped[int] = mapped_column(Integer, nullable=False)


class OffCyclePayrollRunModel(Base):
    __tablename__ = "off_cycle_payroll_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING', 'APPROVED', 'PAID', 'REJECTED')",
            name="ck_off_cycle_payroll_run_status",
        ),
        CheckConstraint(
            "(run_type = 'BENEFIT' AND benefit_type_id IS NOT NULL "
            "AND thirteenth_month_run_id IS NULL) OR "
            "(run_type = 'THIRTEENTH_MONTH' AND benefit_type_id IS NOT NULL "
            "AND thirteenth_month_run_id IS NOT NULL)",
            name="ck_off_cycle_payroll_run_source",
        ),
        Index(
            "ix_off_cycle_payroll_run_paid_company_date",
            "company_id",
            "actual_payment_date",
            postgresql_where=text("status = 'PAID'"),
        ),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.companies.id"), nullable=False
    )
    payroll_group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.payroll_groups.id"), nullable=False
    )
    benefit_type_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.benefit_types.id"), nullable=False
    )
    thirteenth_month_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.thirteenth_month_runs.id"), nullable=True
    )
    run_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'BENEFIT'")
    )
    proposed_payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'DRAFT'")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OffCyclePayrollLineModel(Base):
    __tablename__ = "off_cycle_payroll_lines"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_off_cycle_payroll_line_amount"),
        CheckConstraint(
            "taxable_amount >= 0 AND exempt_limited_amount >= 0 "
            "AND withholding_tax >= 0 AND net_amount >= 0",
            name="ck_off_cycle_payroll_line_tax_amounts",
        ),
        UniqueConstraint(
            "run_id", "employee_id", name="uq_off_cycle_payroll_line_run_employee"
        ),
        Index("ix_off_cycle_payroll_line_13m_result", "thirteenth_month_result_id"),
        Index("ix_off_cycle_payroll_line_employee", "employee_id"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.off_cycle_payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hr.employees.id"), nullable=False
    )
    thirteenth_month_result_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payroll.thirteenth_month_results.id"), nullable=True
    )
    employee_no: Mapped[str] = mapped_column(String(30), nullable=False)
    benefit_code: Mapped[str] = mapped_column(String(30), nullable=False)
    benefit_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(20), nullable=False)
    withholding_timing: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'PAY_PERIOD'")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    exempt_limited_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    withholding_tax: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
