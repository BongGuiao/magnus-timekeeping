from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.infrastructure.dependencies import require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.application.personal_details import (
    EmployeePersonalDetailsInput,
    EmployeePersonalDetailsResponse,
    plan_personal_details_fill,
    save_personal_details,
)
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmployeePersonalDetailsModel,
)

router = APIRouter()


class PersonalDetailsImportRow(EmployeePersonalDetailsInput):
    employee_no: str = Field(min_length=1, max_length=30)


class PersonalDetailsImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[PersonalDetailsImportRow] = Field(min_length=1, max_length=500)
    preview: bool = True


class PersonalDetailsImportResult(BaseModel):
    employee_no: str
    filled_fields: list[str]
    conflicting_fields: list[str]
    status: str


@router.get(
    "/personal-details/template-example",
    response_model=ResponseEnvelope[PersonalDetailsImportRow | None],
)
async def get_personal_details_template_example(
    claims: dict[str, Any] = Depends(require_permission("employees.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        row = (await session.execute(
            select(EmployeeModel.employee_no, EmployeePersonalDetailsModel)
            .join(EmployeeModel, EmployeeModel.id == EmployeePersonalDetailsModel.employee_id)
            .order_by(EmployeePersonalDetailsModel.created_at, EmployeePersonalDetailsModel.employee_id)
            .limit(1)
        )).first()
        if row is None:
            return ResponseEnvelope(data=None)
        employee_no, record = row
        details = EmployeePersonalDetailsResponse.model_validate(record).model_dump(exclude={"employee_id"})
        return ResponseEnvelope(data=PersonalDetailsImportRow(employee_no=employee_no, **details))


@router.get(
    "/{employee_id}/personal-details",
    response_model=ResponseEnvelope[EmployeePersonalDetailsResponse | None],
)
async def get_personal_details(
    employee_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("employees.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        if await session.get(EmployeeModel, employee_id) is None:
            raise HTTPException(status_code=404, detail="Employee not found.")
        record = await session.get(EmployeePersonalDetailsModel, employee_id)
        result = EmployeePersonalDetailsResponse.model_validate(record) if record is not None else None
    return ResponseEnvelope(data=result)


@router.post(
    "/personal-details/import",
    response_model=ResponseEnvelope[list[PersonalDetailsImportResult]],
)
async def import_personal_details(
    payload: PersonalDetailsImportInput,
    claims: dict[str, Any] = Depends(require_permission("employees.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid user identity in authentication token.") from error
    numbers = [row.employee_no for row in payload.rows]
    code_fields = {"psgc_region_code", "psgc_province_code", "psgc_city_code", "psgc_barangay_code"}
    if any(row.model_fields_set & code_fields for row in payload.rows):
        raise HTTPException(status_code=422, detail="PSGC codes must be selected in the employee form, not imported.")
    if len(set(numbers)) != len(numbers):
        raise HTTPException(status_code=422, detail="Duplicate employee numbers in the upload.")
    results: dict[str, PersonalDetailsImportResult] = {}
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        # A stable lock order serializes concurrent imports and form saves.
        employees = (await session.scalars(
            select(EmployeeModel)
            .where(EmployeeModel.employee_no.in_(numbers))
            .order_by(EmployeeModel.employee_no)
            .with_for_update()
        )).all()
        missing = sorted(set(numbers) - {employee.employee_no for employee in employees})
        if missing:
            raise HTTPException(status_code=422, detail=f"Unknown employee numbers: {', '.join(missing)}.")
        rows = {row.employee_no: row for row in payload.rows}
        for employee in employees:
            row = rows[employee.employee_no]
            details = EmployeePersonalDetailsInput.model_validate(
                row.model_dump(exclude={"employee_no"}, exclude_unset=True)
            )
            existing = await session.get(EmployeePersonalDetailsModel, employee.id)
            changes, conflicts = plan_personal_details_fill(existing, details)
            if changes and not payload.preview:
                await save_personal_details(
                    session, employee.id, EmployeePersonalDetailsInput.model_validate(changes), actor_id
                )
            results[employee.employee_no] = PersonalDetailsImportResult(
                employee_no=employee.employee_no,
                filled_fields=list(changes),
                conflicting_fields=conflicts,
                status=("ready" if payload.preview else "updated") if changes else "skipped",
            )
    return ResponseEnvelope(data=[results[number] for number in numbers])
