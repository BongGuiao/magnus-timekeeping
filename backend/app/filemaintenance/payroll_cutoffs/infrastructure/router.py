from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    get_current_user_claims,
    require_permission,
)
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.payroll_cutoffs.application.use_case import (
    CalculateEmployeeCutoffResultsUseCase,
    CreatePayrollCutoffUseCase,
    GetPayrollCutoffUseCase,
    ListPayrollCutoffsUseCase,
    PayrollCutoffConflictError,
    PayrollCutoffReferenceError,
    UpdatePayrollCutoffUseCase,
)
from app.filemaintenance.payroll_cutoffs.domain.entities.payroll_cutoff import PayrollCutoffEntity
from app.filemaintenance.payroll_cutoffs.domain.entities.employee_cutoff_result import (
    EmployeeCutoffResultEntity,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.dependencies import (
    get_calculate_employee_cutoff_results_use_case,
    get_create_payroll_cutoff_use_case,
    get_get_payroll_cutoff_use_case,
    get_list_payroll_cutoffs_use_case,
    get_update_payroll_cutoff_use_case,
)

router = APIRouter(
    prefix="/payroll-cutoffs",
    tags=["Payroll Cutoffs"],
    dependencies=[Depends(require_permission("payroll.manage"))],
)

acknowledgement_router = APIRouter(
    prefix="/payroll-cutoffs",
    tags=["Payroll Cutoff Acknowledgments"],
)


class CreatePayrollCutoffSchema(BaseModel):
    payroll_group_id: UUID
    cutoff_code: str = Field(min_length=1, max_length=50)
    period_start: date
    period_end: date
    pay_date: date
    employee_review_deadline: datetime | None = None
    supervisor_deadline: datetime | None = None
    hr_deadline: datetime | None = None
    status: str = Field(default="SCHEDULED", min_length=1, max_length=30)
    calculation_version: str | None = Field(default=None, max_length=50)
    export_batch_id: UUID | None = None
    is_active: bool = True

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_period(self) -> CreatePayrollCutoffSchema:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start.")
        return self


class UpdatePayrollCutoffSchema(BaseModel):
    id: UUID
    payroll_group_id: UUID | None = None
    cutoff_code: str | None = Field(default=None, min_length=1, max_length=50)
    period_start: date | None = None
    period_end: date | None = None
    pay_date: date | None = None
    employee_review_deadline: datetime | None = None
    supervisor_deadline: datetime | None = None
    hr_deadline: datetime | None = None
    status: str | None = Field(default=None, min_length=1, max_length=30)
    calculation_version: str | None = Field(default=None, max_length=50)
    export_batch_id: UUID | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> UpdatePayrollCutoffSchema:
        nullable_fields = {
            "id",
            "employee_review_deadline",
            "supervisor_deadline",
            "hr_deadline",
            "calculation_version",
            "export_batch_id",
        }
        for field_name in self.model_fields_set - nullable_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end must be on or after period_start.")
        return self


def _actor_id(claims: dict[str, Any]) -> UUID:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def _require_admin(claims: dict[str, Any]) -> None:
    if claims.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role is required to manage payroll cutoffs.",
        )


def _raise_constraint_http_error(error: ValueError) -> None:
    if isinstance(error, PayrollCutoffConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    if isinstance(error, PayrollCutoffReferenceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    raise error


@router.post(
    "/create",
    response_model=ResponseEnvelope[PayrollCutoffEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_payroll_cutoff(
    payload: CreatePayrollCutoffSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreatePayrollCutoffUseCase = Depends(get_create_payroll_cutoff_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = stamp_audit_fields(payload.model_dump(mode="python"), actor_id, creating=True)
    try:
        result = await use_case.execute(values)
    except (PayrollCutoffConflictError, PayrollCutoffReferenceError) as error:
        _raise_constraint_http_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="payroll_cutoff",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[PayrollCutoffEntity],
    status_code=status.HTTP_200_OK,
)
async def update_payroll_cutoff(
    payload: UpdatePayrollCutoffSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdatePayrollCutoffUseCase = Depends(get_update_payroll_cutoff_use_case),
    get_use_case: GetPayrollCutoffUseCase = Depends(get_get_payroll_cutoff_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python", exclude_unset=True, exclude={"id"})
    stamp_audit_fields(values, actor_id, creating=False)
    before = await get_use_case.execute(payload.id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll cutoff not found.")
    try:
        result = await use_case.execute(payload.id, values)
    except (PayrollCutoffConflictError, PayrollCutoffReferenceError) as error:
        _raise_constraint_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll cutoff not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="payroll_cutoff",
        resource_id=payload.id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[PayrollCutoffEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_payroll_cutoffs(
    payroll_group_id: UUID | None = None,
    cutoff_status: str | None = None,
    is_active: bool | None = None,
    period_start_from: date | None = None,
    period_start_to: date | None = None,
    offset: int = 0,
    limit: int = 100,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListPayrollCutoffsUseCase = Depends(get_list_payroll_cutoffs_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    if offset < 0 or not 1 <= limit <= 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="offset must be non-negative and limit must be between 1 and 1000.",
        )
    if period_start_from is not None and period_start_to is not None and period_start_to < period_start_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_start_to must be on or after period_start_from.",
        )
    result = await use_case.execute(
        payroll_group_id,
        cutoff_status,
        is_active,
        period_start_from,
        period_start_to,
        offset,
        limit,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{cutoff_id}",
    response_model=ResponseEnvelope[PayrollCutoffEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_payroll_cutoff(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetPayrollCutoffUseCase = Depends(get_get_payroll_cutoff_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(cutoff_id)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/{cutoff_id}/calculate",
    response_model=ResponseEnvelope[list[EmployeeCutoffResultEntity]],
    status_code=status.HTTP_200_OK,
)
async def calculate_employee_cutoff_results(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CalculateEmployeeCutoffResultsUseCase = Depends(
        get_calculate_employee_cutoff_results_use_case
    ),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    try:
        results = await use_case.calculate(cutoff_id, actor_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CALCULATE",
        resource="employee_cutoff_results",
        resource_id=cutoff_id,
        after={"result_count": len(results), "calculation_version": "TIME_TOTALS_V1"},
    )
    return ResponseEnvelope(status="success", data=results)


@router.get(
    "/{cutoff_id}/results",
    response_model=ResponseEnvelope[list[EmployeeCutoffResultEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_employee_cutoff_results(
    cutoff_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CalculateEmployeeCutoffResultsUseCase = Depends(
        get_calculate_employee_cutoff_results_use_case
    ),
):
    _actor_id(claims)
    _require_admin(claims)
    try:
        results = await use_case.list(cutoff_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ResponseEnvelope(status="success", data=results)


@acknowledgement_router.get(
    "/results/mine",
    response_model=ResponseEnvelope[list[EmployeeCutoffResultEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_my_payroll_cutoff_results(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CalculateEmployeeCutoffResultsUseCase = Depends(
        get_calculate_employee_cutoff_results_use_case
    ),
):
    actor_id = _actor_id(claims)
    try:
        results = await use_case.list_my_results(actor_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ResponseEnvelope(status="success", data=results)


@acknowledgement_router.get(
    "/results/team",
    response_model=ResponseEnvelope[list[EmployeeCutoffResultEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_my_team_payroll_cutoff_results(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CalculateEmployeeCutoffResultsUseCase = Depends(
        get_calculate_employee_cutoff_results_use_case
    ),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
):
    actor_id = _actor_id(claims)
    authorization = await authorization_use_case.execute(actor_id)
    if not {
        "payroll.acknowledge_team",
        "payroll.manage",
    }.intersection(authorization.permission_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    try:
        results = await use_case.list_team_results(actor_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ResponseEnvelope(status="success", data=results)


@acknowledgement_router.post(
    "/{cutoff_id}/results/{result_id}/acknowledge",
    response_model=ResponseEnvelope[EmployeeCutoffResultEntity],
    status_code=status.HTTP_200_OK,
)
async def acknowledge_payroll_cutoff_result(
    cutoff_id: UUID,
    result_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CalculateEmployeeCutoffResultsUseCase = Depends(
        get_calculate_employee_cutoff_results_use_case
    ),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    authorization = await authorization_use_case.execute(actor_id)
    try:
        result = await use_case.acknowledge(
            cutoff_id,
            result_id,
            actor_id,
            can_manage_payroll="payroll.manage" in authorization.permission_codes,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="ACKNOWLEDGE",
        resource="employee_cutoff_results",
        resource_id=result_id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)
