from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.schedule.application.rest_day_pattern_use_case import (
    CreateRestDayPatternUseCase,
    DeleteRestDayPatternUseCase,
    GetRestDayPatternUseCase,
    ListRestDayPatternsUseCase,
    RestDayPatternConflictError,
    RestDayPatternReferenceError,
    RestDayPatternValidationError,
    UpdateRestDayPatternUseCase,
)
from app.filemaintenance.schedule.domain.entities.rest_day_pattern import (
    RestDayPatternEntity,
)
from app.filemaintenance.schedule.infrastructure.dependencies import (
    get_create_rest_day_pattern_use_case,
    get_delete_rest_day_pattern_use_case,
    get_get_rest_day_pattern_use_case,
    get_list_rest_day_patterns_use_case,
    get_update_rest_day_pattern_use_case,
)

router = APIRouter(
    prefix="/rest-day-patterns",
    tags=["Rest Day Patterns"],
    dependencies=[Depends(require_permission("schedule.manage"))],
)


class RestDayPatternDayInput(BaseModel):
    cycle_day_no: int = Field(ge=1, le=366)
    is_workday: bool
    schedule_template_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")


class RestDayPatternInput(BaseModel):
    pattern_code: str = Field(min_length=1, max_length=30)
    pattern_name: str = Field(min_length=1, max_length=100)
    cycle_length_days: int = Field(ge=1, le=366)
    description: str | None = None
    is_active: bool = True
    days: list[RestDayPatternDayInput] = Field(min_length=1, max_length=366)

    model_config = ConfigDict(extra="forbid")

    @field_validator("pattern_code", "pattern_name")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


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
            detail="Administrator role is required to manage rest day patterns.",
        )


def _raise_pattern_error(error: ValueError) -> None:
    if isinstance(error, RestDayPatternConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, (RestDayPatternReferenceError, RestDayPatternValidationError)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    raise error


@router.post(
    "",
    response_model=ResponseEnvelope[RestDayPatternEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_rest_day_pattern(
    payload: RestDayPatternInput,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateRestDayPatternUseCase = Depends(get_create_rest_day_pattern_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python")
    values["days"] = [day.model_dump(mode="python") for day in payload.days]
    try:
        result = await use_case.execute(values)
    except (
        RestDayPatternConflictError,
        RestDayPatternReferenceError,
        RestDayPatternValidationError,
    ) as error:
        _raise_pattern_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="rest_day_pattern",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[RestDayPatternEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_rest_day_patterns(
    is_active: bool | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListRestDayPatternsUseCase = Depends(get_list_rest_day_patterns_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(is_active)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{pattern_id}",
    response_model=ResponseEnvelope[RestDayPatternEntity],
    status_code=status.HTTP_200_OK,
)
async def get_rest_day_pattern(
    pattern_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetRestDayPatternUseCase = Depends(get_get_rest_day_pattern_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(pattern_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rest day pattern not found.")
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/{pattern_id}",
    response_model=ResponseEnvelope[RestDayPatternEntity],
    status_code=status.HTTP_200_OK,
)
async def update_rest_day_pattern(
    pattern_id: UUID,
    payload: RestDayPatternInput,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateRestDayPatternUseCase = Depends(get_update_rest_day_pattern_use_case),
    get_use_case: GetRestDayPatternUseCase = Depends(get_get_rest_day_pattern_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(pattern_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rest day pattern not found.")
    values = payload.model_dump(mode="python")
    values["days"] = [day.model_dump(mode="python") for day in payload.days]
    try:
        result = await use_case.execute(pattern_id, values)
    except (
        RestDayPatternConflictError,
        RestDayPatternReferenceError,
        RestDayPatternValidationError,
    ) as error:
        _raise_pattern_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rest day pattern not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="rest_day_pattern",
        resource_id=pattern_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{pattern_id}",
    response_model=ResponseEnvelope[RestDayPatternEntity],
    status_code=status.HTTP_200_OK,
)
async def delete_rest_day_pattern(
    pattern_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeleteRestDayPatternUseCase = Depends(get_delete_rest_day_pattern_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(pattern_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rest day pattern not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="DELETE",
        resource="rest_day_pattern",
        resource_id=pattern_id,
        before=result,
    )
    return ResponseEnvelope(status="success", data=result)
