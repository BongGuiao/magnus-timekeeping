from datetime import date
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.leaves.application.use_case import (
    CreateLeaveTypeUseCase,
    GetLeaveTypeUseCase,
    ListLeaveTypesUseCase,
    UpdateLeaveTypeUseCase,
)
from app.filemaintenance.leaves.domain.entities.leave_type import LeaveTypeEntity
from app.filemaintenance.leaves.infrastructure.dependencies import (
    get_create_leave_type_use_case,
    get_get_leave_type_use_case,
    get_list_leave_types_use_case,
    get_update_leave_type_use_case,
)

router = APIRouter(prefix="/leave-types", tags=["Leave Types"])


class LeaveTypeFields(BaseModel):
    company_id: UUID
    leave_code: str = Field(min_length=1, max_length=30)
    leave_name: str = Field(min_length=1, max_length=150)
    leave_category: str = Field(min_length=1, max_length=30)
    unit_type: str = Field(min_length=1, max_length=20)
    annual_entitlement_minutes: int = Field(default=0, ge=0)
    accrual_method: str = Field(min_length=1, max_length=30)
    minimum_service_months: int = Field(default=0, ge=0)
    allow_negative_balance: bool = False
    maximum_negative_minutes: int = Field(default=0, ge=0)
    carryover_allowed: bool = False
    maximum_carryover_minutes: int = Field(default=0, ge=0)
    expiry_rule: str = Field(default="NONE", min_length=1, max_length=30)
    cash_conversion_allowed: bool = False
    advance_notice_days: int = Field(default=0, ge=0)
    document_required: bool = False
    document_trigger_minutes: int = Field(default=0, ge=0)
    exclude_rest_days: bool = True
    exclude_holidays: bool = True
    effective_from: date
    effective_to: date | None = None
    status: str = Field(default="ACTIVE", min_length=1, max_length=20)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_effective_dates(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from.")
        return self


class CreateLeaveTypeSchema(LeaveTypeFields):
    pass


class UpdateLeaveTypeSchema(BaseModel):
    id: UUID | None = None
    company_id: UUID | None = None
    leave_code: str | None = Field(default=None, min_length=1, max_length=30)
    leave_name: str | None = Field(default=None, min_length=1, max_length=150)
    leave_category: str | None = Field(default=None, min_length=1, max_length=30)
    unit_type: str | None = Field(default=None, min_length=1, max_length=20)
    annual_entitlement_minutes: int | None = Field(default=None, ge=0)
    accrual_method: str | None = Field(default=None, min_length=1, max_length=30)
    minimum_service_months: int | None = Field(default=None, ge=0)
    allow_negative_balance: bool | None = None
    maximum_negative_minutes: int | None = Field(default=None, ge=0)
    carryover_allowed: bool | None = None
    maximum_carryover_minutes: int | None = Field(default=None, ge=0)
    expiry_rule: str | None = Field(default=None, min_length=1, max_length=30)
    cash_conversion_allowed: bool | None = None
    advance_notice_days: int | None = Field(default=None, ge=0)
    document_required: bool | None = None
    document_trigger_minutes: int | None = Field(default=None, ge=0)
    exclude_rest_days: bool | None = None
    exclude_holidays: bool | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        nullable_fields = {"id", "effective_to"}
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
            detail="Administrator role is required to manage leave policies.",
        )


@router.post(
    "/create",
    response_model=ResponseEnvelope[LeaveTypeEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_leave_type(
    payload: CreateLeaveTypeSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateLeaveTypeUseCase = Depends(get_create_leave_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = stamp_audit_fields(payload.model_dump(mode="python"), actor_id, creating=True)
    result = await use_case.execute(values)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="leave_type",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[LeaveTypeEntity],
    status_code=status.HTTP_200_OK,
)
async def update_leave_type(
    payload: UpdateLeaveTypeSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateLeaveTypeUseCase = Depends(get_update_leave_type_use_case),
    get_use_case: GetLeaveTypeUseCase = Depends(get_get_leave_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    if payload.id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Leave type id is required.",
        )
    leave_type_id = payload.id
    values = payload.model_dump(exclude_unset=True, exclude={"id"})
    stamp_audit_fields(values, actor_id, creating=False)
    before = await get_use_case.execute(leave_type_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave type not found.")
    result = await use_case.execute(leave_type_id, values)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="leave_type",
        resource_id=leave_type_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[LeaveTypeEntity]],
)
async def list_leave_types(
    company_id: UUID | None = None,
    leave_status: str | None = None,
    is_active: bool | None = None,
    leave_code: str | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListLeaveTypesUseCase = Depends(get_list_leave_types_use_case),
):
    _actor_id(claims)
    result = await use_case.execute(company_id, leave_status, is_active, leave_code)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{leave_type_id}",
    response_model=ResponseEnvelope[LeaveTypeEntity],
)
async def get_leave_type(
    leave_type_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetLeaveTypeUseCase = Depends(get_get_leave_type_use_case),
):
    _actor_id(claims)
    result = await use_case.execute(leave_type_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave type not found.")
    return ResponseEnvelope(status="success", data=result)
