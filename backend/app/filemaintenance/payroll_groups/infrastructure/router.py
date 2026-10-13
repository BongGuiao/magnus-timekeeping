from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.payroll_groups.application.use_case import (
    CreatePayrollGroupUseCase,
    GetPayrollGroupUseCase,
    ListPayrollGroupsUseCase,
    PayrollGroupConflictError,
    PayrollGroupReferenceError,
    UpdatePayrollGroupUseCase,
)
from app.filemaintenance.payroll_groups.domain.entities.payroll_group import PayrollGroupEntity
from app.filemaintenance.payroll_groups.infrastructure.dependencies import (
    get_create_payroll_group_use_case,
    get_get_payroll_group_use_case,
    get_list_payroll_groups_use_case,
    get_update_payroll_group_use_case,
)

router = APIRouter(prefix="/payroll-groups", tags=["Payroll Groups"])
PayFrequency = Literal["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"]
RateType = Literal["MONTHLY", "DAILY", "HOURLY"]


def _validate_annual_divisor(value: Decimal | None) -> Decimal | None:
    if value is not None and (
        value.quantize(Decimal("0.01")) != value or value >= Decimal("100000000")
    ):
        raise ValueError("annual_divisor must fit numeric(10,2).")
    return value


class CreatePayrollGroupSchema(BaseModel):
    company_id: UUID
    payroll_group_code: str = Field(min_length=1, max_length=30)
    payroll_group_name: str = Field(min_length=1, max_length=100)
    pay_frequency: PayFrequency
    rate_type: RateType
    standard_minutes_per_day: int = Field(default=480, gt=0)
    annual_divisor: Decimal | None = Field(default=None, gt=0)
    rounding_minutes: int = Field(default=1, gt=0)
    holiday_calendar_id: UUID | None = None
    status: str = Field(default="ACTIVE", min_length=1, max_length=20)
    is_active: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("annual_divisor")
    @classmethod
    def validate_annual_divisor(cls, value: Decimal | None) -> Decimal | None:
        return _validate_annual_divisor(value)


class UpdatePayrollGroupSchema(BaseModel):
    id: UUID
    company_id: UUID | None = None
    payroll_group_code: str | None = Field(default=None, min_length=1, max_length=30)
    payroll_group_name: str | None = Field(default=None, min_length=1, max_length=100)
    pay_frequency: PayFrequency | None = None
    rate_type: RateType | None = None
    standard_minutes_per_day: int | None = Field(default=None, gt=0)
    annual_divisor: Decimal | None = Field(default=None, gt=0)
    rounding_minutes: int | None = Field(default=None, gt=0)
    holiday_calendar_id: UUID | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("annual_divisor")
    @classmethod
    def validate_annual_divisor(cls, value: Decimal | None) -> Decimal | None:
        return _validate_annual_divisor(value)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> UpdatePayrollGroupSchema:
        nullable_fields = {"id", "annual_divisor", "holiday_calendar_id"}
        for field_name in self.model_fields_set - nullable_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
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
            detail="Administrator role is required to manage payroll groups.",
        )


def _raise_constraint_http_error(error: ValueError) -> None:
    if isinstance(error, PayrollGroupConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    if isinstance(error, PayrollGroupReferenceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    raise error


@router.post(
    "/create",
    response_model=ResponseEnvelope[PayrollGroupEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_payroll_group(
    payload: CreatePayrollGroupSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreatePayrollGroupUseCase = Depends(get_create_payroll_group_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = stamp_audit_fields(payload.model_dump(mode="python"), actor_id, creating=True)
    try:
        result = await use_case.execute(values)
    except (PayrollGroupConflictError, PayrollGroupReferenceError) as error:
        _raise_constraint_http_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="payroll_group",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[PayrollGroupEntity],
    status_code=status.HTTP_200_OK,
)
async def update_payroll_group(
    payload: UpdatePayrollGroupSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdatePayrollGroupUseCase = Depends(get_update_payroll_group_use_case),
    get_use_case: GetPayrollGroupUseCase = Depends(get_get_payroll_group_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python", exclude_unset=True, exclude={"id"})
    stamp_audit_fields(values, actor_id, creating=False)
    before = await get_use_case.execute(payload.id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll group not found.")
    try:
        result = await use_case.execute(payload.id, values)
    except (PayrollGroupConflictError, PayrollGroupReferenceError) as error:
        _raise_constraint_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll group not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="payroll_group",
        resource_id=payload.id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[PayrollGroupEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_payroll_groups(
    company_id: UUID | None = None,
    group_status: str | None = None,
    is_active: bool | None = None,
    offset: int = 0,
    limit: int = 100,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListPayrollGroupsUseCase = Depends(get_list_payroll_groups_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    if offset < 0 or not 1 <= limit <= 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="offset must be non-negative and limit must be between 1 and 1000.",
        )
    result = await use_case.execute(company_id, group_status, is_active, offset, limit)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{payroll_group_id}",
    response_model=ResponseEnvelope[PayrollGroupEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_payroll_group(
    payroll_group_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetPayrollGroupUseCase = Depends(get_get_payroll_group_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(payroll_group_id)
    return ResponseEnvelope(status="success", data=result)
