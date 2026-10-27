from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, NoReturn
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth.application.authorization import PH_TIMEZONE
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import (
    get_current_user_claims,
    require_permission,
)
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.companies.application.use_case import ListCompaniesUseCase
from app.filemaintenance.companies.domain.entities.company import CompanyEntity
from app.filemaintenance.companies.infrastructure.dependencies import get_list_companies_use_case
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel
from app.payroll.application.use_cases import (
    CreateCompensationInput,
    PayrollCutoffNotFoundError,
    PayrollUseCases,
    SaveEarningRuleInput,
    UpdateCompensationInput,
)
from app.payroll.domain.entities.gross_payroll import (
    PayrollCutoffLockState,
    ThirteenthMonthRun,
)
from app.payroll.infrastructure.dependencies import get_payroll_use_cases
from app.payroll.infrastructure.db_model import PayrollSystemParametersModel

payroll_manage_router = APIRouter(
    prefix="/payroll",
    tags=["Payroll"],
    dependencies=[Depends(require_permission("payroll.manage"))],
)

payroll_employee_router = APIRouter(prefix="/payroll", tags=["Payroll"])

payroll_system_parameters_router = APIRouter(
    prefix="/payroll",
    tags=["Payroll system parameters"],
    dependencies=[Depends(require_permission("payroll.company_parameters.manage"))],
)


async def _require_company_payroll_permission(
    uow: GenUnitOfWork,
    *,
    user_id: UUID,
    company_id: UUID,
    permission_code: str,
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    today = datetime.now(PH_TIMEZONE).date()
    assignment_id = await uow.session.scalar(
        select(UserRoleModel.id)
        .select_from(UserRoleModel)
        .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
        .join(UserModel, UserModel.id == UserRoleModel.user_id)
        .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
        .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
        .where(
            UserRoleModel.user_id == user_id,
            UserRoleModel.effective_from <= today,
            or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= today),
            or_(
                UserRoleModel.company_id == company_id,
                and_(
                    UserRoleModel.company_id.is_(None),
                    RoleModel.role_code.in_(("SYSTEM_ADMIN", "SYSTEM_ADMINISTRATOR")),
                ),
            ),
            RoleModel.is_active.is_(True),
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            RolePermissionModel.allowed.is_(True),
            PermissionModel.permission_code == permission_code,
            PermissionModel.is_active.is_(True),
        )
        .limit(1)
    )
    if assignment_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage payroll settings for this company.",
        )
PayComponent = Literal[
    "REGULAR",
    "PAID_LEAVE",
    "OFFICIAL_BUSINESS",
    "REST_DAY",
    "SPECIAL_DAY",
    "HOLIDAY",
    "ORDINARY_OT",
    "REST_DAY_OT",
    "SPECIAL_DAY_OT",
    "HOLIDAY_OT",
    "NIGHT_REGULAR",
    "NIGHT_OT",
]
GrossPayLineComponent = Literal[
    "REGULAR",
    "PAID_LEAVE",
    "OFFICIAL_BUSINESS",
    "REST_DAY",
    "SPECIAL_DAY",
    "HOLIDAY",
    "ORDINARY_OT",
    "REST_DAY_OT",
    "SPECIAL_DAY_OT",
    "HOLIDAY_OT",
    "NIGHT_REGULAR",
    "NIGHT_OT",
    "MONTHLY_BASE",
    "UNPAID_TIME_DEDUCTION",
]


class CompensationCreateSchema(BaseModel):
    employee_id: UUID
    payroll_group_id: UUID
    base_rate: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Rate amount in the payroll group's configured monthly, daily, or hourly unit.",
    )
    currency: str = Field(default="PHP", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    effective_from: date
    effective_to: date | None = None

    model_config = ConfigDict(extra="forbid")


class CompensationUpdateSchema(BaseModel):
    base_rate: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Rate amount in the payroll group's configured monthly, daily, or hourly unit.",
    )
    currency: str = Field(default="PHP", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    effective_from: date
    effective_to: date | None = None

    model_config = ConfigDict(extra="forbid")


class CompensationSchema(BaseModel):
    id: UUID
    employee_id: UUID
    payroll_group_id: UUID
    base_rate: Decimal
    currency: str
    effective_from: date
    effective_to: date | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class EarningRuleWriteSchema(BaseModel):
    payroll_group_id: UUID
    component_code: PayComponent
    multiplier: Decimal = Field(
        ge=0,
        max_digits=8,
        decimal_places=4,
        description=(
            "Use the full pay-rate multiplier for overtime/day components. NIGHT_REGULAR and "
            "NIGHT_OT are premium-only add-ons; configure their differential (for example 0.10), "
            "not the combined base-plus-premium rate."
        ),
    )

    model_config = ConfigDict(extra="forbid")


class EarningRuleSchema(BaseModel):
    component_code: PayComponent
    multiplier: Decimal

    model_config = ConfigDict(from_attributes=True)


class PayrollSystemParametersSchema(BaseModel):
    company_id: UUID
    year_end_wtax_reconciliation_enabled: bool
    thirteenth_month_enabled: bool
    schedule_assignment_approval_required: bool
    statutory_contribution_timing: Literal["PER_CUTOFF", "FINAL_CUTOFF"]
    updated_at: datetime
    updated_by: UUID | None

    model_config = ConfigDict(from_attributes=True)


class PayrollSystemParametersUpdateSchema(BaseModel):
    year_end_wtax_reconciliation_enabled: bool
    thirteenth_month_enabled: bool
    schedule_assignment_approval_required: bool
    statutory_contribution_timing: Literal["PER_CUTOFF", "FINAL_CUTOFF"]

    model_config = ConfigDict(extra="forbid")


class ThirteenthMonthRunRequestSchema(BaseModel):
    company_id: UUID
    tax_year: int = Field(ge=1900, le=9999)
    covered_period_from: date
    covered_period_to: date

    @model_validator(mode="after")
    def validate_covered_period(self) -> "ThirteenthMonthRunRequestSchema":
        if self.covered_period_from > self.covered_period_to:
            raise ValueError("The covered cutoff start date must be on or before its end date.")
        if (
            self.covered_period_from.year != self.tax_year
            or self.covered_period_to.year != self.tax_year
        ):
            raise ValueError("The covered cutoff dates must be within the selected tax year.")
        return self

    model_config = ConfigDict(extra="forbid")


class ThirteenthMonthResultSchema(BaseModel):
    employee_id: UUID
    employee_no: str
    employee_name: str
    basic_salary_earned: Decimal
    thirteenth_month_pay: Decimal
    tax_exempt_amount: Decimal
    taxable_amount: Decimal
    source_payroll_periods: int


class ThirteenthMonthRunSchema(BaseModel):
    id: UUID
    tax_year: int
    covered_period_from: date
    covered_period_to: date
    calculated_at: datetime
    calculated_by: UUID
    results: list[ThirteenthMonthResultSchema]

    @classmethod
    def from_entity(cls, run: ThirteenthMonthRun) -> "ThirteenthMonthRunSchema":
        return cls(
            id=run.id,
            tax_year=run.tax_year,
            covered_period_from=run.covered_period_from,
            covered_period_to=run.covered_period_to,
            calculated_at=run.calculated_at,
            calculated_by=run.calculated_by,
            results=run.results,
        )


class GrossPayLineSchema(BaseModel):
    component_code: GrossPayLineComponent
    minutes: int
    multiplier: Decimal
    amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class PayrollBenefitLineSchema(BaseModel):
    benefit_code: str
    benefit_name: str
    category: Literal[
        "CASH_ALLOWANCE",
        "ONE_TIME_BONUS",
        "REIMBURSEMENT",
        "EMPLOYER_PAID_INSURANCE",
        "NON_CASH",
        "EMPLOYEE_DEDUCTION",
    ]
    tax_treatment: Literal["TAXABLE", "EXEMPT", "EXEMPT_LIMITED"]
    withholding_timing: Literal["PAY_PERIOD", "YEAR_END"]
    amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class PayrollContributionLineSchema(BaseModel):
    program_code: Literal["SSS", "PHILHEALTH", "PAGIBIG"]
    employee_amount: Decimal
    employer_amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class GrossPayResultSchema(BaseModel):
    employee_id: UUID
    cutoff_result_id: UUID
    currency: str | None
    base_rate: Decimal | None
    gross_amount: Decimal | None
    status: Literal["HOLD", "READY"]
    gross_status: Literal["HOLD", "READY"] | None = None
    hold_reason: str | None
    cash_benefit_amount: Decimal | None = None
    non_cash_benefit_amount: Decimal | None = None
    employee_benefit_deductions: Decimal | None = None
    exempt_limited_benefit_amount: Decimal | None = None
    taxable_income: Decimal | None = None
    employee_contributions: Decimal | None = None
    employer_contributions: Decimal | None = None
    withholding_tax: Decimal | None = None
    net_amount: Decimal | None = None
    lines: list[GrossPayLineSchema]
    source_minutes: dict[str, int]
    benefit_lines: list[PayrollBenefitLineSchema] = Field(default_factory=list)
    contribution_lines: list[PayrollContributionLineSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class GrossPayRunSchema(BaseModel):
    id: UUID
    cutoff_id: UUID
    calculation_version: str
    calculated_at: datetime
    calculated_by: UUID
    results: list[GrossPayResultSchema]

    model_config = ConfigDict(from_attributes=True)


class PayrollCutoffLockStateSchema(BaseModel):
    cutoff_id: UUID
    locked: bool
    locked_at: datetime | None
    locked_by: UUID | None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_entity(cls, lock_state: PayrollCutoffLockState) -> "PayrollCutoffLockStateSchema":
        return cls(
            cutoff_id=lock_state.cutoff_id,
            locked=lock_state.locked,
            locked_at=lock_state.locked_at,
            locked_by=lock_state.locked_by,
        )


def _get_actor_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error


def _raise_payroll_error(error: ValueError) -> NoReturn:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@payroll_manage_router.post(
    "/compensations",
    response_model=ResponseEnvelope[CompensationSchema],
    status_code=status.HTTP_201_CREATED,
    description=(
        "Creates an effective-dated employee rate only when exactly one active employment "
        "assignment to the selected payroll group covers every date in the rate period."
    ),
)
async def create_compensation(
    payload: CompensationCreateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    try:
        compensation = await use_cases.create_compensation(
            CreateCompensationInput(
                employee_id=payload.employee_id,
                payroll_group_id=payload.payroll_group_id,
                base_rate=payload.base_rate,
                currency=payload.currency,
                effective_from=payload.effective_from,
                effective_to=payload.effective_to,
                actor_id=actor_id,
            )
        )
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="employee_compensation",
        resource_id=compensation.id,
        after={
            "employee_id": str(compensation.employee_id),
            "payroll_group_id": str(compensation.payroll_group_id),
            "currency": compensation.currency,
            "effective_from": compensation.effective_from.isoformat(),
            "effective_to": compensation.effective_to.isoformat() if compensation.effective_to else None,
        },
    )
    return ResponseEnvelope(status="success", data=compensation)


@payroll_manage_router.put(
    "/compensations/{compensation_id}",
    response_model=ResponseEnvelope[CompensationSchema],
    description=(
        "Updates an employee rate while preserving its employee and payroll-group association. "
        "The updated effective period must be covered by exactly one active assignment and must "
        "not overlap another active compensation."
    ),
)
async def update_compensation(
    compensation_id: UUID,
    payload: CompensationUpdateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    try:
        compensation = await use_cases.update_compensation(
            UpdateCompensationInput(
                compensation_id=compensation_id,
                base_rate=payload.base_rate,
                currency=payload.currency,
                effective_from=payload.effective_from,
                effective_to=payload.effective_to,
                actor_id=actor_id,
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="employee_compensation",
        resource_id=compensation.id,
        after={
            "base_rate": str(compensation.base_rate),
            "currency": compensation.currency,
            "effective_from": compensation.effective_from.isoformat(),
            "effective_to": compensation.effective_to.isoformat() if compensation.effective_to else None,
        },
    )
    return ResponseEnvelope(status="success", data=compensation)


@payroll_manage_router.get(
    "/compensations",
    response_model=ResponseEnvelope[list[CompensationSchema]],
)
async def list_compensations(
    payroll_group_id: UUID,
    employee_id: UUID | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
):
    _get_actor_id(claims)
    result = await use_cases.list_compensations(employee_id, payroll_group_id)
    return ResponseEnvelope(status="success", data=result)


@payroll_manage_router.put(
    "/earning-rules",
    response_model=ResponseEnvelope[EarningRuleSchema],
    description=(
        "Creates or replaces one payroll-group earning multiplier. All supported components "
        "must be configured before gross calculation can proceed."
    ),
)
async def save_earning_rule(
    payload: EarningRuleWriteSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    try:
        rule = await use_cases.save_earning_rule(
            SaveEarningRuleInput(
                payroll_group_id=payload.payroll_group_id,
                component_code=payload.component_code,
                multiplier=payload.multiplier,
                actor_id=actor_id,
            )
        )
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="payroll_earning_rule",
        resource_id=payload.payroll_group_id,
        after={"component_code": rule.component_code},
    )
    return ResponseEnvelope(status="success", data=rule)


@payroll_manage_router.get(
    "/earning-rules",
    response_model=ResponseEnvelope[list[EarningRuleSchema]],
)
async def list_earning_rules(
    payroll_group_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
):
    _get_actor_id(claims)
    return ResponseEnvelope(
        status="success",
        data=await use_cases.list_earning_rules(payroll_group_id),
    )


@payroll_system_parameters_router.get(
    "/system-parameters/companies",
    response_model=ResponseEnvelope[list[CompanyEntity]],
)
async def list_payroll_parameter_companies(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListCompaniesUseCase = Depends(get_list_companies_use_case),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor_id = _get_actor_id(claims)
    today = datetime.now(PH_TIMEZONE).date()
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        authorized_company_ids = set(
            (
                await uow.session.scalars(
                    select(CompanyModel.id)
                    .join(
                        UserRoleModel,
                        or_(
                            UserRoleModel.company_id == CompanyModel.id,
                            UserRoleModel.company_id.is_(None),
                        ),
                    )
                    .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                    .join(UserModel, UserModel.id == UserRoleModel.user_id)
                    .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
                    .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
                    .where(
                        UserRoleModel.user_id == actor_id,
                        UserRoleModel.effective_from <= today,
                        or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= today),
                        or_(
                            UserRoleModel.company_id == CompanyModel.id,
                            and_(
                                UserRoleModel.company_id.is_(None),
                                RoleModel.role_code.in_(("SYSTEM_ADMIN", "SYSTEM_ADMINISTRATOR")),
                            ),
                        ),
                        RoleModel.is_active.is_(True),
                        UserModel.is_active.is_(True),
                        UserModel.account_status == "ACTIVE",
                        RolePermissionModel.allowed.is_(True),
                        PermissionModel.permission_code == "payroll.company_parameters.manage",
                        PermissionModel.is_active.is_(True),
                    )
                    .distinct()
                )
            ).all()
        )
        assigned_company_ids = set(
            (
                await uow.session.scalars(
                    select(EmploymentAssignmentModel.company_id)
                    .join(
                        EmployeeModel,
                        EmployeeModel.id == EmploymentAssignmentModel.employee_id,
                    )
                    .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                    .where(
                        UserModel.id == actor_id,
                        UserModel.is_active.is_(True),
                        UserModel.account_status == "ACTIVE",
                        EmployeeModel.is_active.is_(True),
                        EmployeeModel.record_status == "ACTIVE",
                        EmploymentAssignmentModel.is_active.is_(True),
                        EmploymentAssignmentModel.status == "ACTIVE",
                        EmploymentAssignmentModel.effective_from <= today,
                        or_(
                            EmploymentAssignmentModel.effective_to.is_(None),
                            EmploymentAssignmentModel.effective_to >= today,
                        ),
                    )
                    .distinct()
                )
            ).all()
        )
    companies = await use_case.execute()
    return ResponseEnvelope(
        status="success",
        data=[
            company
            for company in companies
            if company.is_active
            and company.id in authorized_company_ids
            and company.id in assigned_company_ids
        ],
    )


@payroll_system_parameters_router.get(
    "/system-parameters",
    response_model=ResponseEnvelope[PayrollSystemParametersSchema],
)
async def get_payroll_system_parameters(
    company_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor_id = _get_actor_id(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        await _require_company_payroll_permission(
            uow,
            user_id=actor_id,
            company_id=company_id,
            permission_code="payroll.company_parameters.manage",
        )
        company = await uow.session.get(CompanyModel, company_id)
        if company is None or not company.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found.",
            )
        await uow.session.execute(
            pg_insert(PayrollSystemParametersModel)
            .values(company_id=company_id)
            .on_conflict_do_nothing(index_elements=[PayrollSystemParametersModel.company_id])
        )
        parameters = await uow.session.get(PayrollSystemParametersModel, company_id)
        if parameters is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payroll system parameters could not be initialized for this company.",
            )
        return ResponseEnvelope(status="success", data=parameters)


@payroll_system_parameters_router.put(
    "/system-parameters",
    response_model=ResponseEnvelope[PayrollSystemParametersSchema],
)
async def update_payroll_system_parameters(
    payload: PayrollSystemParametersUpdateSchema,
    company_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        await _require_company_payroll_permission(
            uow,
            user_id=actor_id,
            company_id=company_id,
            permission_code="payroll.company_parameters.manage",
        )
        company = await uow.session.get(CompanyModel, company_id)
        if company is None or not company.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found.",
            )
        await uow.session.execute(
            pg_insert(PayrollSystemParametersModel)
            .values(company_id=company_id)
            .on_conflict_do_nothing(index_elements=[PayrollSystemParametersModel.company_id])
        )
        parameters = await uow.session.scalar(
            select(PayrollSystemParametersModel)
            .where(PayrollSystemParametersModel.company_id == company_id)
            .with_for_update()
        )
        if parameters is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payroll system parameters could not be initialized for this company.",
            )
        before = {
            "year_end_wtax_reconciliation_enabled": (
                parameters.year_end_wtax_reconciliation_enabled
            ),
            "thirteenth_month_enabled": parameters.thirteenth_month_enabled,
            "schedule_assignment_approval_required": (
                parameters.schedule_assignment_approval_required
            ),
            "statutory_contribution_timing": parameters.statutory_contribution_timing,
        }
        parameters.year_end_wtax_reconciliation_enabled = (
            payload.year_end_wtax_reconciliation_enabled
        )
        parameters.thirteenth_month_enabled = payload.thirteenth_month_enabled
        parameters.schedule_assignment_approval_required = (
            payload.schedule_assignment_approval_required
        )
        parameters.statutory_contribution_timing = payload.statutory_contribution_timing
        parameters.updated_by = actor_id
        await uow.session.flush()
        await uow.session.refresh(parameters)
        response_data = PayrollSystemParametersSchema.model_validate(parameters)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="payroll_system_parameters",
        resource_id=str(company_id),
        before=before,
        after={
            "year_end_wtax_reconciliation_enabled": (
                payload.year_end_wtax_reconciliation_enabled
            ),
            "thirteenth_month_enabled": payload.thirteenth_month_enabled,
            "schedule_assignment_approval_required": (
                payload.schedule_assignment_approval_required
            ),
            "statutory_contribution_timing": payload.statutory_contribution_timing,
        },
    )
    return ResponseEnvelope(status="success", data=response_data)


@payroll_manage_router.post(
    "/thirteenth-month-runs/calculate",
    response_model=ResponseEnvelope[ThirteenthMonthRunSchema],
    description=(
        "Calculates statutory 13th-month pay as eligible basic salary earned in the tax year "
        "divided by 12. The active withholding-tax schedule's benefit exemption limit is shared "
        "with other qualifying benefits; taxable excess is included in the final December "
        "cutoff's year-end tax reconciliation."
    ),
)
async def calculate_thirteenth_month_run(
    payload: ThirteenthMonthRunRequestSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    async with uow:
        await _require_company_payroll_permission(
            uow,
            user_id=actor_id,
            company_id=payload.company_id,
            permission_code="payroll.manage",
        )
    try:
        run = await use_cases.calculate_thirteenth_month(
            payload.company_id,
            payload.tax_year,
            payload.covered_period_from,
            payload.covered_period_to,
            actor_id,
        )
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CALCULATE",
        resource="payroll_thirteenth_month",
        resource_id=run.id,
        after={
            "tax_year": run.tax_year,
            "result_count": len(run.results),
            "calculation_version": "THIRTEENTH_MONTH_V1",
        },
    )
    return ResponseEnvelope(
        status="success",
        data=ThirteenthMonthRunSchema.from_entity(run),
    )


@payroll_manage_router.post(
    "/cutoffs/{cutoff_id}/calculate",
    response_model=ResponseEnvelope[GrossPayRunSchema],
    description=(
        "Calculates gross pay and complete net-pay breakdowns. Results remain on HOLD with "
        "net_amount unset until active contribution and withholding-tax schedules cover the "
        "cutoff; missing schedules are never inferred or seeded."
    ),
)
@payroll_manage_router.post(
    "/cutoffs/{cutoff_id}/calculate-gross",
    response_model=ResponseEnvelope[GrossPayRunSchema],
    description=(
        "Compatibility route for calculating payroll gross pay and net-pay breakdowns."
    ),
)
async def calculate_cutoff_gross_pay(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    try:
        run = await use_cases.calculate_payroll(cutoff_id, actor_id)
    except PayrollCutoffNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CALCULATE",
        resource="payroll_net_pay",
        resource_id=run.id,
        after={
            "cutoff_id": str(cutoff_id),
            "calculation_version": run.calculation_version,
            "result_count": len(run.results),
        },
    )
    return ResponseEnvelope(status="success", data=run)


@payroll_manage_router.post(
    "/cutoffs/{cutoff_id}/approve",
    response_model=ResponseEnvelope[PayrollCutoffLockStateSchema],
    dependencies=[Depends(require_permission("payroll.approve"))],
)
async def approve_payroll_cutoff(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    try:
        lock_state = await use_cases.approve_payroll_cutoff(cutoff_id, actor_id)
    except PayrollCutoffNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="APPROVE",
        resource="payroll_cutoff",
        resource_id=cutoff_id,
        after=lock_state,
    )
    return ResponseEnvelope(
        status="success",
        data=PayrollCutoffLockStateSchema.from_entity(lock_state),
    )


@payroll_manage_router.post(
    "/cutoffs/{cutoff_id}/unlock",
    response_model=ResponseEnvelope[PayrollCutoffLockStateSchema],
    dependencies=[Depends(require_permission("payroll.approve"))],
)
async def unlock_payroll_cutoff(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_actor_id(claims)
    try:
        lock_state = await use_cases.unlock_payroll_cutoff(cutoff_id, actor_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        _raise_payroll_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UNLOCK",
        resource="payroll_cutoff",
        resource_id=cutoff_id,
        after=lock_state,
    )
    return ResponseEnvelope(
        status="success",
        data=PayrollCutoffLockStateSchema.from_entity(lock_state),
    )


@payroll_manage_router.get(
    "/cutoffs/{cutoff_id}/gross-results",
    response_model=ResponseEnvelope[GrossPayRunSchema | None],
)
async def get_cutoff_gross_pay(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
):
    _get_actor_id(claims)
    run = await use_cases.get_current_gross_pay_run(cutoff_id)
    return ResponseEnvelope(status="success", data=run)


@payroll_employee_router.get(
    "/gross-results/mine",
    response_model=ResponseEnvelope[list[GrossPayRunSchema]],
    dependencies=[Depends(require_permission("payroll.read_own"))],
)
async def list_my_gross_pay_results(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: PayrollUseCases = Depends(get_payroll_use_cases),
):
    return ResponseEnvelope(
        status="success",
        data=await use_cases.list_my_gross_pay_results(_get_actor_id(claims)),
    )
