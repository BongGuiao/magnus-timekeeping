from datetime import date
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.domain.entities.user import RoleEntity, UserRoleEntity
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.roles.application.payroll_access import PayrollAccessViolationError
from app.filemaintenance.roles.application.use_case import (
    CreateUserRoleUseCase,
    GetUserRoleUseCase,
    ListAvailableRolesUseCase,
    ListUserRolesUseCase,
    UpdateUserRoleUseCase,
    UserRoleReferenceError,
)
from app.filemaintenance.roles.infrastructure.dependencies import (
    get_create_user_role_use_case,
    get_get_user_role_use_case,
    get_list_available_roles_use_case,
    get_list_user_roles_use_case,
    get_update_user_role_use_case,
)

router = APIRouter(
    prefix="/user-roles",
    tags=["User Roles"],
    dependencies=[Depends(require_permission("system.manage"))],
)


class CreateUserRoleSchema(BaseModel):
    user_id: UUID
    role_id: UUID
    company_id: UUID | None = None
    org_unit_id: UUID | None = None
    effective_from: date
    effective_to: date | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_effective_dates(self) -> "CreateUserRoleSchema":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from.")
        return self


class UpdateUserRoleSchema(BaseModel):
    id: UUID
    user_id: UUID | None = None
    role_id: UUID | None = None
    company_id: UUID | None = None
    org_unit_id: UUID | None = None
    effective_from: date | None = None
    effective_to: date | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_update(self) -> "UpdateUserRoleSchema":
        nullable_fields = {"id", "company_id", "org_unit_id", "effective_to"}
        for field_name in self.model_fields_set - nullable_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must be on or after effective_from.")
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
            detail="Administrator role is required to manage user roles.",
        )


def _raise_reference_http_error(error: UserRoleReferenceError) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(error),
    ) from error


@router.post(
    "/create",
    response_model=ResponseEnvelope[UserRoleEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_user_role(
    payload: CreateUserRoleSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateUserRoleUseCase = Depends(get_create_user_role_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python")
    values["assigned_by"] = actor_id
    try:
        result = await use_case.execute(values)
    except PayrollAccessViolationError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except UserRoleReferenceError as error:
        _raise_reference_http_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="user_role",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[UserRoleEntity],
    status_code=status.HTTP_200_OK,
)
async def update_user_role(
    payload: UpdateUserRoleSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateUserRoleUseCase = Depends(get_update_user_role_use_case),
    get_use_case: GetUserRoleUseCase = Depends(get_get_user_role_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python", exclude_unset=True, exclude={"id"})
    before = await get_use_case.execute(payload.id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User role not found.")
    try:
        result = await use_case.execute(payload.id, values, actor_id)
    except PayrollAccessViolationError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except UserRoleReferenceError as error:
        _raise_reference_http_error(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User role not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="user_role",
        resource_id=payload.id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[UserRoleEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_user_roles(
    user_id: UUID | None = None,
    role_id: UUID | None = None,
    company_id: UUID | None = None,
    org_unit_id: UUID | None = None,
    effective_on: date | None = None,
    offset: int = 0,
    limit: int = 100,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListUserRolesUseCase = Depends(get_list_user_roles_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    if offset < 0 or not 1 <= limit <= 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="offset must be non-negative and limit must be between 1 and 1000.",
        )
    result = await use_case.execute(
        user_id,
        role_id,
        company_id,
        org_unit_id,
        effective_on,
        offset,
        limit,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/available-roles",
    response_model=ResponseEnvelope[list[RoleEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_available_roles(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListAvailableRolesUseCase = Depends(get_list_available_roles_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute()
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{user_role_id}",
    response_model=ResponseEnvelope[UserRoleEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_user_role(
    user_role_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetUserRoleUseCase = Depends(get_get_user_role_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(user_role_id)
    return ResponseEnvelope(status="success", data=result)
