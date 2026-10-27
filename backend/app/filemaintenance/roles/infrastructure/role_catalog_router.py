from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.domain.entities.user import RoleEntity
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.roles.application.payroll_access import PayrollAccessViolationError
from app.filemaintenance.roles.application.use_case import (
    CreateRoleUseCase,
    DeactivateRoleUseCase,
    GetRoleUseCase,
    ListRolesUseCase,
    RoleConflictError,
    UpdateRoleUseCase,
)
from app.filemaintenance.roles.application.permission_use_cases import (
    GetRolePermissionsUseCase,
    ListPermissionsUseCase,
    SetRolePermissionsUseCase,
    UnknownPermissionCodesError,
)
from app.filemaintenance.roles.infrastructure.dependencies import (
    get_create_role_use_case,
    get_deactivate_role_use_case,
    get_get_role_use_case,
    get_list_roles_use_case,
    get_get_role_permissions_use_case,
    get_list_permissions_use_case,
    get_set_role_permissions_use_case,
    get_update_role_use_case,
)

router = APIRouter(
    prefix="/roles",
    tags=["Roles"],
    dependencies=[Depends(require_permission("system.manage"))],
)


class CreateRoleSchema(BaseModel):
    role_code: str = Field(min_length=1, max_length=50)
    role_name: str = Field(min_length=1, max_length=100)
    scope_type: str = Field(min_length=1, max_length=30)
    description: str | None = None
    is_system_role: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("role_code", "role_name", "scope_type")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("role_code")
    @classmethod
    def normalize_role_code(cls, value: str) -> str:
        return value.upper()


class UpdateRoleSchema(BaseModel):
    id: UUID
    role_code: str | None = Field(default=None, min_length=1, max_length=50)
    role_name: str | None = Field(default=None, min_length=1, max_length=100)
    scope_type: str | None = Field(default=None, min_length=1, max_length=30)
    description: str | None = None
    is_system_role: bool | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("role_code", "role_name", "scope_type")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("role_code")
    @classmethod
    def normalize_role_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else value

    @model_validator(mode="after")
    def validate_null_fields(self) -> "UpdateRoleSchema":
        nullable_fields = {"id", "description"}
        for field_name in self.model_fields_set - nullable_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        return self


class PermissionResponseSchema(BaseModel):
    permission_code: str
    module_code: str
    action_code: str | None
    permission_name: str
    description: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SetRolePermissionsSchema(BaseModel):
    permission_codes: list[str]

    model_config = ConfigDict(extra="forbid")

    @field_validator("permission_codes")
    @classmethod
    def validate_permission_codes(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Permission codes cannot be blank.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Permission codes must not contain duplicates.")
        return normalized


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
            detail="Administrator role is required to manage roles.",
        )


def _raise_role_conflict(error: RoleConflictError) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get(
    "/permissions/list",
    response_model=ResponseEnvelope[list[PermissionResponseSchema]],
)
async def list_permissions(
    claims: dict[str, Any] = Depends(require_permission("system.manage")),
    use_case: ListPermissionsUseCase = Depends(get_list_permissions_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    permissions = await use_case.execute()
    return ResponseEnvelope(status="success", data=permissions)


@router.get(
    "/permissions/by-role/{role_id}",
    response_model=ResponseEnvelope[list[str]],
)
async def get_role_permissions(
    role_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("system.manage")),
    use_case: GetRolePermissionsUseCase = Depends(get_get_role_permissions_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    permission_codes = await use_case.execute(role_id)
    if permission_codes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    return ResponseEnvelope(status="success", data=permission_codes)


@router.put(
    "/permissions/by-role/{role_id}",
    response_model=ResponseEnvelope[list[str]],
)
async def set_role_permissions(
    role_id: UUID,
    payload: SetRolePermissionsSchema,
    claims: dict[str, Any] = Depends(require_permission("system.manage")),
    use_case: SetRolePermissionsUseCase = Depends(get_set_role_permissions_use_case),
    get_use_case: GetRolePermissionsUseCase = Depends(get_get_role_permissions_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(role_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    try:
        permission_codes = await use_case.execute(role_id, payload.permission_codes)
    except PayrollAccessViolationError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    except UnknownPermissionCodesError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    if permission_codes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="role_permissions",
        resource_id=role_id,
        before={"permission_codes": before},
        after={"permission_codes": permission_codes},
    )
    return ResponseEnvelope(status="success", data=permission_codes)


@router.post(
    "/create",
    response_model=ResponseEnvelope[RoleEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    payload: CreateRoleSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateRoleUseCase = Depends(get_create_role_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = stamp_audit_fields(payload.model_dump(mode="python"), actor_id, creating=True)
    try:
        result = await use_case.execute(values)
    except RoleConflictError as error:
        _raise_role_conflict(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="role",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[RoleEntity],
    status_code=status.HTTP_200_OK,
)
async def update_role(
    payload: UpdateRoleSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateRoleUseCase = Depends(get_update_role_use_case),
    get_use_case: GetRoleUseCase = Depends(get_get_role_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = payload.model_dump(mode="python", exclude_unset=True, exclude={"id"})
    stamp_audit_fields(values, actor_id, creating=False)
    before = await get_use_case.execute(payload.id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    try:
        result = await use_case.execute(payload.id, values)
    except RoleConflictError as error:
        _raise_role_conflict(error)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="role",
        resource_id=payload.id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[RoleEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_roles(
    is_active: bool | None = None,
    role_code: str | None = Query(default=None, min_length=1, max_length=50),
    offset: int = 0,
    limit: int = 100,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListRolesUseCase = Depends(get_list_roles_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    if offset < 0 or not 1 <= limit <= 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="offset must be non-negative and limit must be between 1 and 1000.",
        )
    result = await use_case.execute(is_active, role_code, offset, limit)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{role_id}",
    response_model=ResponseEnvelope[RoleEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_role(
    role_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetRoleUseCase = Depends(get_get_role_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(role_id)
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{role_id}",
    response_model=ResponseEnvelope[RoleEntity],
    status_code=status.HTTP_200_OK,
)
async def deactivate_role(
    role_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeactivateRoleUseCase = Depends(get_deactivate_role_use_case),
    get_use_case: GetRoleUseCase = Depends(get_get_role_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(role_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    try:
        result = await use_case.execute(role_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="DEACTIVATE",
        resource="role",
        resource_id=role_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)
