from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, NoReturn
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import (
    get_current_user_claims,
    require_any_permission,
    require_permission,
)
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.payroll.application.off_cycle_inputs import (
    CreateOffCycleBenefitRunInput,
    CreateThirteenthMonthOffCycleRunInput,
    OffCycleUploadRow,
    ThirteenthMonthRunSummary,
)
from app.payroll.application.off_cycle_use_cases import (
    MAX_OFF_CYCLE_UPLOAD_ROWS,
    OffCyclePayrollUseCases,
)
from app.payroll.domain.entities.off_cycle import OffCyclePayrollLine, OffCyclePayrollRun
from app.payroll.infrastructure.off_cycle_dependencies import get_off_cycle_payroll_use_cases
from app.payroll.infrastructure.router import _require_company_payroll_permission


MANAGE = "payroll.manage"
APPROVE = "payroll.approve"

router = APIRouter(
    prefix="/payroll/off-cycle-runs",
    tags=["Payroll off-cycle runs"],
    dependencies=[Depends(require_any_permission(MANAGE, APPROVE))],
)

OffCycleStatusValue = Literal["DRAFT", "PENDING", "APPROVED", "PAID", "REJECTED"]


class OffCycleUploadRowSchema(BaseModel):
    employee_no: str = Field(min_length=1, max_length=30)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class CreateOffCycleBenefitRunSchema(BaseModel):
    payroll_group_id: UUID
    benefit_type_id: UUID
    proposed_payment_date: date
    notes: str | None = Field(default=None, max_length=500)
    rows: list[OffCycleUploadRowSchema] = Field(min_length=1, max_length=MAX_OFF_CYCLE_UPLOAD_ROWS)

    model_config = ConfigDict(extra="forbid")


class CreateThirteenthMonthOffCycleRunSchema(BaseModel):
    payroll_group_id: UUID
    benefit_type_id: UUID
    thirteenth_month_run_id: UUID
    proposed_payment_date: date
    notes: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class RejectOffCycleRunSchema(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


class MarkOffCycleRunPaidSchema(BaseModel):
    actual_payment_date: date

    model_config = ConfigDict(extra="forbid")


class OffCycleLineSchema(BaseModel):
    id: UUID
    employee_id: UUID
    employee_no: str
    employee_name: str
    benefit_code: str
    benefit_name: str
    category: str
    tax_treatment: str
    withholding_timing: str
    amount: Decimal
    taxable_amount: Decimal
    exempt_limited_amount: Decimal
    withholding_tax: Decimal
    net_amount: Decimal
    notes: str | None
    thirteenth_month_result_id: UUID | None

    @classmethod
    def from_entity(cls, line: OffCyclePayrollLine) -> "OffCycleLineSchema":
        return cls(
            id=line.id,
            employee_id=line.employee_id,
            employee_no=line.employee_no,
            employee_name=line.employee_name,
            benefit_code=line.benefit_code,
            benefit_name=line.benefit_name,
            category=line.category,
            tax_treatment=line.tax_treatment,
            withholding_timing=line.withholding_timing,
            amount=line.amount,
            taxable_amount=line.taxable_amount,
            exempt_limited_amount=line.exempt_limited_amount,
            withholding_tax=line.withholding_tax,
            net_amount=line.net_amount,
            notes=line.notes,
            thirteenth_month_result_id=line.thirteenth_month_result_id,
        )


class OffCycleRunSchema(BaseModel):
    id: UUID
    company_id: UUID
    payroll_group_id: UUID
    benefit_type_id: UUID
    benefit_code: str
    benefit_name: str
    run_type: str
    status: OffCycleStatusValue
    proposed_payment_date: date
    actual_payment_date: date | None
    notes: str | None
    rejection_reason: str | None
    created_by: UUID
    created_at: datetime
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    paid_by: UUID | None
    paid_at: datetime | None
    thirteenth_month_run_id: UUID | None
    employee_count: int
    total_amount: Decimal
    total_withholding_tax: Decimal
    total_net_amount: Decimal
    lines: list[OffCycleLineSchema]

    @classmethod
    def from_entity(
        cls, run: OffCyclePayrollRun, *, include_lines: bool = True
    ) -> "OffCycleRunSchema":
        return cls(
            id=run.id,
            company_id=run.company_id,
            payroll_group_id=run.payroll_group_id,
            benefit_type_id=run.benefit_type_id,
            benefit_code=run.benefit_code,
            benefit_name=run.benefit_name,
            run_type=run.run_type,
            status=run.status,
            proposed_payment_date=run.proposed_payment_date,
            actual_payment_date=run.actual_payment_date,
            notes=run.notes,
            rejection_reason=run.rejection_reason,
            created_by=run.created_by,
            created_at=run.created_at,
            submitted_at=run.submitted_at,
            approved_by=run.approved_by,
            approved_at=run.approved_at,
            paid_by=run.paid_by,
            paid_at=run.paid_at,
            thirteenth_month_run_id=run.thirteenth_month_run_id,
            employee_count=len(run.lines),
            total_amount=run.total_amount,
            total_withholding_tax=run.total_withholding_tax,
            total_net_amount=run.total_net_amount,
            lines=[OffCycleLineSchema.from_entity(line) for line in run.lines]
            if include_lines
            else [],
        )


class ThirteenthMonthRunSummarySchema(BaseModel):
    id: UUID
    tax_year: int
    covered_period_from: date | None
    covered_period_to: date | None
    calculated_at: datetime
    result_count: int

    @classmethod
    def from_entity(cls, item: ThirteenthMonthRunSummary) -> "ThirteenthMonthRunSummarySchema":
        return cls(
            id=item.id,
            tax_year=item.tax_year,
            covered_period_from=item.covered_period_from,
            covered_period_to=item.covered_period_to,
            calculated_at=item.calculated_at,
            result_count=item.result_count,
        )


def _actor_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error


def _raise_error(error: Exception) -> NoReturn:
    if isinstance(error, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, PermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


async def _require_company_permission(
    uow: GenUnitOfWork,
    *,
    user_id: UUID,
    company_id: UUID,
    permission_codes: tuple[str, ...],
) -> None:
    denied: HTTPException | None = None
    for permission_code in permission_codes:
        try:
            async with uow:
                await _require_company_payroll_permission(
                    uow,
                    user_id=user_id,
                    company_id=company_id,
                    permission_code=permission_code,
                )
            return
        except HTTPException as error:
            denied = error
    if denied is not None:
        raise denied


async def _authorize_group(
    use_cases: OffCyclePayrollUseCases,
    uow: GenUnitOfWork,
    *,
    actor_id: UUID,
    payroll_group_id: UUID,
    permission_codes: tuple[str, ...],
) -> None:
    try:
        company_id = await use_cases.get_payroll_group_company_id(payroll_group_id)
    except LookupError as error:
        _raise_error(error)
    await _require_company_permission(
        uow, user_id=actor_id, company_id=company_id, permission_codes=permission_codes
    )


async def _authorize_run(
    use_cases: OffCyclePayrollUseCases,
    uow: GenUnitOfWork,
    *,
    actor_id: UUID,
    run_id: UUID,
    permission_codes: tuple[str, ...],
) -> OffCyclePayrollRun:
    try:
        run = await use_cases.get_run(run_id)
    except LookupError as error:
        _raise_error(error)
    await _require_company_permission(
        uow, user_id=actor_id, company_id=run.company_id, permission_codes=permission_codes
    )
    return run


async def _audit(
    es_client: AsyncElasticsearch | None,
    *,
    actor_id: UUID,
    action: str,
    run: OffCyclePayrollRun,
) -> None:
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action=action,
        resource="payroll_off_cycle_run",
        resource_id=run.id,
        after={
            "status": run.status,
            "run_type": run.run_type,
            "benefit_code": run.benefit_code,
            "proposed_payment_date": run.proposed_payment_date.isoformat(),
            "actual_payment_date": (
                run.actual_payment_date.isoformat() if run.actual_payment_date else None
            ),
            "employee_count": len(run.lines),
            "total_amount": str(run.total_amount),
            "total_withholding_tax": str(run.total_withholding_tax),
        },
    )


@router.get("", response_model=ResponseEnvelope[list[OffCycleRunSchema]])
async def list_off_cycle_runs(
    company_id: UUID = Query(...),
    payroll_group_id: UUID | None = Query(default=None),
    run_status: OffCycleStatusValue | None = Query(default=None, alias="status"),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    await _require_company_permission(
        uow,
        user_id=_actor_id(claims),
        company_id=company_id,
        permission_codes=(MANAGE, APPROVE),
    )
    runs = await use_cases.list_runs(
        company_id=company_id, payroll_group_id=payroll_group_id, status=run_status
    )
    return ResponseEnvelope(
        status="success",
        data=[OffCycleRunSchema.from_entity(run, include_lines=False) for run in runs],
    )


@router.get(
    "/thirteenth-month-sources",
    response_model=ResponseEnvelope[list[ThirteenthMonthRunSummarySchema]],
)
async def list_thirteenth_month_sources(
    payroll_group_id: UUID = Query(...),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    await _authorize_group(
        use_cases,
        uow,
        actor_id=_actor_id(claims),
        payroll_group_id=payroll_group_id,
        permission_codes=(MANAGE,),
    )
    runs = await use_cases.list_thirteenth_month_runs(payroll_group_id)
    return ResponseEnvelope(
        status="success",
        data=[ThirteenthMonthRunSummarySchema.from_entity(item) for item in runs],
    )


@router.get("/{run_id}", response_model=ResponseEnvelope[OffCycleRunSchema])
async def get_off_cycle_run(
    run_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    run = await _authorize_run(
        use_cases,
        uow,
        actor_id=_actor_id(claims),
        run_id=run_id,
        permission_codes=(MANAGE, APPROVE),
    )
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(MANAGE))],
    description=(
        "Creates a draft off-cycle run from uploaded rows for one benefit type. "
        "Tax treatment and withholding timing follow the benefit type configuration."
    ),
)
async def create_off_cycle_benefit_run(
    payload: CreateOffCycleBenefitRunSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_group(
        use_cases,
        uow,
        actor_id=actor_id,
        payroll_group_id=payload.payroll_group_id,
        permission_codes=(MANAGE,),
    )
    try:
        run = await use_cases.create_benefit_run(
            CreateOffCycleBenefitRunInput(
                payroll_group_id=payload.payroll_group_id,
                benefit_type_id=payload.benefit_type_id,
                proposed_payment_date=payload.proposed_payment_date,
                notes=payload.notes,
                actor_id=actor_id,
                rows=tuple(
                    OffCycleUploadRow(
                        employee_no=row.employee_no,
                        amount=row.amount,
                        notes=row.notes,
                    )
                    for row in payload.rows
                ),
            )
        )
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="CREATE", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "/thirteenth-month",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(MANAGE))],
    description=(
        "Creates a draft off-cycle run that pays the current 13th-month results. "
        "Withholding uses the cumulative year-to-date method so tax on earlier "
        "incentives deferred to year end is collected."
    ),
)
async def create_thirteenth_month_off_cycle_run(
    payload: CreateThirteenthMonthOffCycleRunSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_group(
        use_cases,
        uow,
        actor_id=actor_id,
        payroll_group_id=payload.payroll_group_id,
        permission_codes=(MANAGE,),
    )
    try:
        run = await use_cases.create_thirteenth_month_run(
            CreateThirteenthMonthOffCycleRunInput(
                payroll_group_id=payload.payroll_group_id,
                benefit_type_id=payload.benefit_type_id,
                thirteenth_month_run_id=payload.thirteenth_month_run_id,
                proposed_payment_date=payload.proposed_payment_date,
                notes=payload.notes,
                actor_id=actor_id,
            )
        )
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="CREATE", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "/{run_id}/recalculate",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    dependencies=[Depends(require_permission(MANAGE))],
)
async def recalculate_off_cycle_run(
    run_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_run(
        use_cases, uow, actor_id=actor_id, run_id=run_id, permission_codes=(MANAGE,)
    )
    try:
        run = await use_cases.recalculate_run(run_id)
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="RECALCULATE", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "/{run_id}/submit",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    dependencies=[Depends(require_permission(MANAGE))],
)
async def submit_off_cycle_run(
    run_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_run(
        use_cases, uow, actor_id=actor_id, run_id=run_id, permission_codes=(MANAGE,)
    )
    try:
        run = await use_cases.submit_run(run_id, actor_id)
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="SUBMIT", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "/{run_id}/approve",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    dependencies=[Depends(require_permission(APPROVE))],
    description="Approves a submitted run. The user who prepared the run cannot approve it.",
)
async def approve_off_cycle_run(
    run_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_run(
        use_cases, uow, actor_id=actor_id, run_id=run_id, permission_codes=(APPROVE,)
    )
    try:
        run = await use_cases.approve_run(run_id, actor_id)
    except (LookupError, PermissionError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="APPROVE", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "/{run_id}/reject",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    dependencies=[Depends(require_permission(APPROVE))],
)
async def reject_off_cycle_run(
    run_id: UUID,
    payload: RejectOffCycleRunSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_run(
        use_cases, uow, actor_id=actor_id, run_id=run_id, permission_codes=(APPROVE,)
    )
    try:
        run = await use_cases.reject_run(run_id, actor_id, payload.reason)
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="REJECT", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.post(
    "/{run_id}/mark-paid",
    response_model=ResponseEnvelope[OffCycleRunSchema],
    dependencies=[Depends(require_permission(MANAGE))],
    description=(
        "Records the actual release date. Year-to-date tax and year-end reconciliation "
        "use this date."
    ),
)
async def mark_off_cycle_run_paid(
    run_id: UUID,
    payload: MarkOffCycleRunPaidSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_run(
        use_cases, uow, actor_id=actor_id, run_id=run_id, permission_codes=(MANAGE,)
    )
    try:
        run = await use_cases.mark_run_paid(run_id, actor_id, payload.actual_payment_date)
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="MARK_PAID", run=run)
    return ResponseEnvelope(status="success", data=OffCycleRunSchema.from_entity(run))


@router.delete(
    "/{run_id}",
    response_model=ResponseEnvelope[dict[str, bool]],
    dependencies=[Depends(require_permission(MANAGE))],
)
async def delete_off_cycle_run(
    run_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_cases: OffCyclePayrollUseCases = Depends(get_off_cycle_payroll_use_cases),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    await _authorize_run(
        use_cases, uow, actor_id=actor_id, run_id=run_id, permission_codes=(MANAGE,)
    )
    try:
        run = await use_cases.delete_run(run_id)
    except (LookupError, ValueError) as error:
        _raise_error(error)
    await _audit(es_client, actor_id=actor_id, action="DELETE", run=run)
    return ResponseEnvelope(status="success", data={"deleted": True})
