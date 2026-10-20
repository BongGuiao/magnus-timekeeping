from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, NoReturn
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import (
    get_current_user_claims,
    require_permission,
)
from app.core.generics.mapper import ResponseEnvelope
from app.payroll.application.use_cases import (
    CreateCompensationInput,
    PayrollCutoffNotFoundError,
    PayrollUseCases,
    SaveEarningRuleInput,
    UpdateCompensationInput,
)
from app.payroll.infrastructure.dependencies import get_payroll_use_cases

payroll_manage_router = APIRouter(
    prefix="/payroll",
    tags=["Payroll"],
    dependencies=[Depends(require_permission("payroll.manage"))],
)

payroll_employee_router = APIRouter(prefix="/payroll", tags=["Payroll"])

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


class GrossPayLineSchema(BaseModel):
    component_code: PayComponent
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
