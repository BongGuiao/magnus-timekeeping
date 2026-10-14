from __future__ import annotations

from datetime import date, time
from typing import Any, Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.schedule.application.use_case import (
    CreateScheduleSegmentUseCase,
    CreateScheduleTemplateUseCase,
    DeleteScheduleSegmentUseCase,
    GetScheduleSegmentUseCase,
    GetScheduleTemplateUseCase,
    ListScheduleSegmentsUseCase,
    ListScheduleTemplatesUseCase,
    ScheduleSegmentConflictError,
    ScheduleSegmentReferenceError,
    ScheduleTemplateConflictError,
    ScheduleTemplateReferenceError,
    ScheduleTemplateValidationError,
    UpdateScheduleSegmentUseCase,
    UpdateScheduleTemplateUseCase,
)
from app.filemaintenance.schedule.domain.entities.schedule_segment import (
    ScheduleSegmentEntity,
    ScheduleSegmentType,
)
from app.filemaintenance.schedule.domain.entities.schedule_template import (
    ScheduleTemplateEntity,
    ScheduleType,
)
from app.filemaintenance.schedule.infrastructure.dependencies import (
    get_create_schedule_segment_use_case,
    get_create_schedule_template_use_case,
    get_delete_schedule_segment_use_case,
    get_get_schedule_segment_use_case,
    get_get_schedule_template_use_case,
    get_list_schedule_segments_use_case,
    get_list_schedule_templates_use_case,
    get_update_schedule_segment_use_case,
    get_update_schedule_template_use_case,
)

router = APIRouter(
    prefix="/schedule-templates",
    tags=["Schedule Templates"],
    dependencies=[Depends(require_permission("schedule.manage"))],
)


class CreateScheduleSegmentSchema(BaseModel):
    segment_sequence: int = Field(ge=-32768, le=32767)
    segment_type: ScheduleSegmentType
    start_time: time
    end_time: time
    end_day_offset: int = Field(default=0, ge=0, le=2)
    paid_minutes: int = Field(default=0, ge=0)
    punch_required: bool = False
    auto_deduct: bool = False
    flex_start_minutes: int = Field(default=0, ge=0)
    break_slot: Literal["FIRST_BREAK", "MEAL_BREAK", "SECOND_BREAK"] | None = None
    work_segment_sequence: int | None = Field(default=None, ge=1, le=32767)
    break_minutes: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class UpdateScheduleSegmentSchema(BaseModel):
    segment_sequence: int | None = Field(default=None, ge=-32768, le=32767)
    segment_type: ScheduleSegmentType | None = None
    start_time: time | None = None
    end_time: time | None = None
    end_day_offset: int | None = Field(default=None, ge=0, le=2)
    paid_minutes: int | None = Field(default=None, ge=0)
    punch_required: bool | None = None
    auto_deduct: bool | None = None
    flex_start_minutes: int | None = Field(default=None, ge=0)
    break_slot: Literal["FIRST_BREAK", "MEAL_BREAK", "SECOND_BREAK"] | None = None
    work_segment_sequence: int | None = Field(default=None, ge=1, le=32767)
    break_minutes: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_null_fields(self) -> UpdateScheduleSegmentSchema:
        for field_name in self.model_fields_set:
            if field_name not in ("break_slot", "work_segment_sequence") and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        return self


class CreateScheduleTemplateSchema(BaseModel):
    company_id: UUID
    schedule_code: str = Field(min_length=1, max_length=30)
    schedule_name: str = Field(min_length=1, max_length=150)
    schedule_type: ScheduleType
    required_minutes: int = Field(gt=0)
    grace_minutes: int = Field(default=0, ge=0)
    grace_method: str = Field(default="NONE", min_length=1, max_length=30)
    is_overnight: bool = False
    ot_eligible: bool = True
    pre_shift_ot_allowed: bool = False
    minimum_ot_minutes: int = Field(default=0, ge=0)
    holiday_calendar_id: UUID | None = None
    effective_from: date
    effective_to: date | None = None
    status: str = Field(default="DRAFT", min_length=1, max_length=20)
    is_active: bool = True

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_effective_period(self) -> CreateScheduleTemplateSchema:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from.")
        return self


class UpdateScheduleTemplateSchema(BaseModel):
    id: UUID
    company_id: UUID | None = None
    schedule_code: str | None = Field(default=None, min_length=1, max_length=30)
    schedule_name: str | None = Field(default=None, min_length=1, max_length=150)
    schedule_type: ScheduleType | None = None
    required_minutes: int | None = Field(default=None, gt=0)
    grace_minutes: int | None = Field(default=None, ge=0)
    grace_method: str | None = Field(default=None, min_length=1, max_length=30)
    is_overnight: bool | None = None
    ot_eligible: bool | None = None
    pre_shift_ot_allowed: bool | None = None
    minimum_ot_minutes: int | None = Field(default=None, ge=0)
    holiday_calendar_id: UUID | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> UpdateScheduleTemplateSchema:
        nullable_fields = {"id", "holiday_calendar_id", "effective_to"}
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
            detail="Administrator role is required to manage schedule templates.",
        )


def _raise_constraint_http_error(error: ValueError) -> None:
    if isinstance(error, ScheduleSegmentConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, ScheduleSegmentReferenceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    if isinstance(error, ScheduleTemplateConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, ScheduleTemplateReferenceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    if isinstance(error, ScheduleTemplateValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    raise error


@router.post(
    "/{template_id}/segments",
    response_model=ResponseEnvelope[ScheduleSegmentEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule_segment(
    template_id: UUID,
    payload: CreateScheduleSegmentSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateScheduleSegmentUseCase = Depends(get_create_schedule_segment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    try:
        result = await use_case.execute(template_id, payload.model_dump(mode="python"))
    except (ScheduleSegmentConflictError, ScheduleSegmentReferenceError) as error:
        _raise_constraint_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="schedule_segment",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{template_id}/segments",
    response_model=ResponseEnvelope[list[ScheduleSegmentEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_schedule_segments(
    template_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListScheduleSegmentsUseCase = Depends(get_list_schedule_segments_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(template_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{template_id}/segments/{segment_id}",
    response_model=ResponseEnvelope[ScheduleSegmentEntity],
    status_code=status.HTTP_200_OK,
)
async def get_schedule_segment(
    template_id: UUID,
    segment_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetScheduleSegmentUseCase = Depends(get_get_schedule_segment_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(template_id, segment_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule segment not found.")
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/{template_id}/segments/{segment_id}",
    response_model=ResponseEnvelope[ScheduleSegmentEntity],
    status_code=status.HTTP_200_OK,
)
async def update_schedule_segment(
    template_id: UUID,
    segment_id: UUID,
    payload: UpdateScheduleSegmentSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateScheduleSegmentUseCase = Depends(get_update_schedule_segment_use_case),
    get_use_case: GetScheduleSegmentUseCase = Depends(get_get_schedule_segment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(template_id, segment_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule segment not found.")
    values = payload.model_dump(mode="python", exclude_unset=True)
    try:
        result = await use_case.execute(template_id, segment_id, values)
    except (ScheduleSegmentConflictError, ScheduleSegmentReferenceError) as error:
        _raise_constraint_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule segment not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="schedule_segment",
        resource_id=segment_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{template_id}/segments/{segment_id}",
    response_model=ResponseEnvelope[ScheduleSegmentEntity],
    status_code=status.HTTP_200_OK,
)
async def delete_schedule_segment(
    template_id: UUID,
    segment_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeleteScheduleSegmentUseCase = Depends(get_delete_schedule_segment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    try:
        result = await use_case.execute(template_id, segment_id)
    except ScheduleSegmentReferenceError as error:
        _raise_constraint_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule segment not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="DELETE",
        resource="schedule_segment",
        resource_id=segment_id,
        before=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/create",
    response_model=ResponseEnvelope[ScheduleTemplateEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule_template(
    payload: CreateScheduleTemplateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateScheduleTemplateUseCase = Depends(get_create_schedule_template_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = stamp_audit_fields(payload.model_dump(mode="python"), actor_id, creating=True)
    try:
        result = await use_case.execute(values)
    except (
        ScheduleTemplateConflictError,
        ScheduleTemplateReferenceError,
        ScheduleTemplateValidationError,
    ) as error:
        _raise_constraint_http_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="schedule_template",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[ScheduleTemplateEntity],
    status_code=status.HTTP_200_OK,
)
async def update_schedule_template(
    payload: UpdateScheduleTemplateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateScheduleTemplateUseCase = Depends(get_update_schedule_template_use_case),
    get_use_case: GetScheduleTemplateUseCase = Depends(get_get_schedule_template_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python", exclude_unset=True, exclude={"id"})
    stamp_audit_fields(values, actor_id, creating=False)
    before = await get_use_case.execute(payload.id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    try:
        result = await use_case.execute(payload.id, values)
    except (
        ScheduleTemplateConflictError,
        ScheduleTemplateReferenceError,
        ScheduleTemplateValidationError,
    ) as error:
        _raise_constraint_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="schedule_template",
        resource_id=payload.id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[ScheduleTemplateEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_schedule_templates(
    company_id: UUID | None = None,
    schedule_type: ScheduleType | None = None,
    template_status: str | None = None,
    is_active: bool | None = None,
    effective_from: date | None = None,
    effective_to: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListScheduleTemplatesUseCase = Depends(get_list_schedule_templates_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    if effective_from is not None and effective_to is not None and effective_to < effective_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="effective_to must be on or after effective_from.",
        )
    result = await use_case.execute(
        company_id,
        schedule_type,
        template_status,
        is_active,
        effective_from,
        effective_to,
        offset,
        limit,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{template_id}",
    response_model=ResponseEnvelope[ScheduleTemplateEntity],
    status_code=status.HTTP_200_OK,
)
async def get_schedule_template(
    template_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetScheduleTemplateUseCase = Depends(get_get_schedule_template_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(template_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{template_id}",
    response_model=ResponseEnvelope[ScheduleTemplateEntity],
    status_code=status.HTTP_200_OK,
)
async def deactivate_schedule_template(
    template_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateScheduleTemplateUseCase = Depends(get_update_schedule_template_use_case),
    get_use_case: GetScheduleTemplateUseCase = Depends(get_get_schedule_template_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(template_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    values = stamp_audit_fields({"is_active": False}, actor_id, creating=False)
    result = await use_case.execute(template_id, values)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule template not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="schedule_template",
        resource_id=template_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)
