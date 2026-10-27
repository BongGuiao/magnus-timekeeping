from typing import Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    get_current_user_claims,
    require_permission,
)
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmployeeWfhLocationModel,
    EmploymentAssignmentGeofenceModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.location.infrastructure.db_model import Location
from app.filemaintenance.employees.application.use_case import (
    CreateEmployeeUseCase,
    GetEmployeeUseCase,
    ListEmployeesUseCase,
    UpdateEmployeeUseCase,
)
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.infrastructure.dependencies import (
    get_create_employee_use_case,
    get_employee_use_case,
    get_list_employees_use_case,
    get_update_employee_use_case,
)

router = APIRouter(prefix="/employees", tags=["Employees"])


def _require_email(claims: dict[str, Any]) -> None:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )


def _get_user_id(claims: dict[str, Any]) -> UUID:
    _require_email(claims)
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def resolve_employee_read_scope(
    claims: dict[str, Any],
    permission_codes: list[str] | set[str],
) -> UUID | None:
    """Return None for organisation-wide access, or the supervisor's employee id for team scope."""
    if "employees.read" in permission_codes:
        return None
    if "employees.read_team" in permission_codes:
        try:
            return UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not linked to an employee record.",
            ) from error
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")


class EmployeeWfhInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    geofence_id: UUID
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_active: bool = True


class EmployeeWfhResponse(EmployeeWfhInput):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)

    employee_id: UUID
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    row_version: int


@router.get("/{employee_id}/wfh", response_model=ResponseEnvelope[EmployeeWfhResponse | None])
async def get_employee_wfh(
    employee_id: UUID,
    claims: dict = Depends(require_permission("employees.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _get_user_id(claims)
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        record = await session.get(EmployeeWfhLocationModel, employee_id)
        result = EmployeeWfhResponse.model_validate(record) if record else None
    return ResponseEnvelope(data=result)


@router.put("/{employee_id}/wfh", response_model=ResponseEnvelope[EmployeeWfhResponse])
async def save_employee_wfh(
    employee_id: UUID,
    payload: EmployeeWfhInput,
    claims: dict = Depends(require_permission("employees.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Manila")).date()
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        employee = await session.get(EmployeeModel, employee_id)
        if employee is None:
            raise ValueError("Employee not found.")
        if payload.is_active:
            if not employee.is_active or employee.record_status != "ACTIVE":
                raise ValueError("WFH registration requires an active employee.")
            fence = await session.scalar(
                select(Geofence)
                .join(Location, Location.id == Geofence.location_id)
                .join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.company_id == Geofence.company_id
                )
                .join(
                    EmploymentAssignmentGeofenceModel,
                    (EmploymentAssignmentGeofenceModel.assignment_id == EmploymentAssignmentModel.id)
                    & (EmploymentAssignmentGeofenceModel.geofence_id == Geofence.id)
                    & (EmploymentAssignmentGeofenceModel.company_id == Geofence.company_id),
                )
                .where(
                    Geofence.id == payload.geofence_id,
                    Geofence.company_id == Location.company_id,
                    Geofence.is_active.is_(True),
                    Geofence.status == "ACTIVE",
                    Geofence.effective_from <= now,
                    or_(Geofence.effective_to.is_(None), Geofence.effective_to >= now),
                    Geofence.radius_meters > 0,
                    Location.is_active.is_(True),
                    Location.status == "ACTIVE",
                    EmploymentAssignmentModel.employee_id == employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= today),
                    or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= today),
                )
            )
            if fence is None:
                raise ValueError("Select an active assigned geofence with a radius for this employee.")
        elif await session.get(Geofence, payload.geofence_id) is None:
            raise ValueError("Geofence not found.")
        record = await session.scalar(
            select(EmployeeWfhLocationModel)
            .where(EmployeeWfhLocationModel.employee_id == employee_id)
            .with_for_update()
        )
        before = EmployeeWfhResponse.model_validate(record) if record else None
        if record is None:
            record = EmployeeWfhLocationModel(
                employee_id=employee_id, **payload.model_dump(),
                created_by=actor_id, updated_by=actor_id,
                created_at=now, updated_at=now, row_version=1,
            )
            session.add(record)
        else:
            record.geofence_id = payload.geofence_id
            record.latitude = payload.latitude
            record.longitude = payload.longitude
            record.is_active = payload.is_active
            record.updated_by = actor_id
            record.updated_at = now
            record.row_version += 1
        await session.flush()
        result = EmployeeWfhResponse.model_validate(record)
    await log_entity_action(
        es_client, user_id=actor_id,
        action="UPDATE" if before else "CREATE",
        resource="employee_wfh_location", resource_id=employee_id,
        before=before, after=result,
    )
    return ResponseEnvelope(data=result)


@router.post(
    "/create",
    response_model=ResponseEnvelope[EmployeeEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_permission("employees.manage")),
    use_case: CreateEmployeeUseCase = Depends(get_create_employee_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    result = await use_case.execute(
        stamp_audit_fields(payload, user_id, creating=True)
    )
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="employee",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[EmployeeEntity],
    status_code=status.HTTP_200_OK,
)
async def update_employee(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_permission("employees.manage")),
    use_case: UpdateEmployeeUseCase = Depends(get_update_employee_use_case),
    get_use_case: GetEmployeeUseCase = Depends(get_employee_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    stamp_audit_fields(payload, user_id, creating=False)

    employee_id = payload.pop("id", None)
    if not employee_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Employee id is required.",
        )
    try:
        parsed_employee_id = UUID(str(employee_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Employee id must be a UUID.",
        ) from error

    before = await get_use_case.execute(parsed_employee_id)
    result = await use_case.execute(parsed_employee_id, payload)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="employee",
        resource_id=parsed_employee_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[EmployeeEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_employees(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
    use_case: ListEmployeesUseCase = Depends(get_list_employees_use_case),
):
    user_id = _get_user_id(claims)
    authorization = await authorization_use_case.execute(user_id)
    supervisor_employee_id = resolve_employee_read_scope(claims, authorization.permission_codes)
    result = await use_case.execute(supervisor_employee_id)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{employee_id}",
    response_model=ResponseEnvelope[EmployeeEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_employee(
    employee_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
    use_case: GetEmployeeUseCase = Depends(get_employee_use_case),
):
    user_id = _get_user_id(claims)
    authorization = await authorization_use_case.execute(user_id)
    supervisor_employee_id = resolve_employee_read_scope(claims, authorization.permission_codes)
    result = await use_case.execute(employee_id, supervisor_employee_id)
    return ResponseEnvelope(status="success", data=result)
