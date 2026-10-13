from dataclasses import fields, replace
from datetime import date
from typing import Any
from uuid import UUID

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.companies.domain.entities.company import CompanyEntity
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.domain.entities.employee_skill import EmployeeSkillEntity
from app.filemaintenance.employees.domain.entities.employment_assignment import EmploymentAssignmentEntity
from app.filemaintenance.employees.infrastructure.db_model import (
    OPERATIONAL_GROUPS,
    EmployeeModel,
    EmployeeSkillModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.location.domain.entities.location import LocationEntity
from app.filemaintenance.location.infrastructure.db_model import Location
from app.filemaintenance.payroll_groups.domain.entities.payroll_group import PayrollGroupEntity
from app.filemaintenance.payroll_groups.infrastructure.db_model import PayrollGroupModel

ASSIGNMENT_DATE_FIELDS = ("hire_date", "effective_from", "effective_to", "separation_date")
ASSIGNMENT_UUID_FIELDS = (
    "id",
    "employee_id",
    "company_id",
    "org_unit_id",
    "position_id",
    "supervisor_employee_id",
    "payroll_group_id",
    "primary_location_id",
    "created_by",
    "updated_by",
)
SKILL_DATE_FIELDS = ("issued_date", "expiry_date")
SKILL_UUID_FIELDS = ("id", "employee_id", "verified_by", "created_by", "updated_by")
PROTECTED_FIELDS = ("id", "employee_id", "created_at", "created_by", "row_version")


def _normalize(payload: dict[str, Any], date_fields: tuple[str, ...], uuid_fields: tuple[str, ...]) -> dict[str, Any]:
    normalized = payload.copy()
    for field in date_fields:
        value = normalized.get(field)
        if isinstance(value, str):
            try:
                normalized[field] = date.fromisoformat(value) if value else None
            except ValueError as error:
                raise ValueError(f"{field} must be a valid date (YYYY-MM-DD).") from error
    for field in uuid_fields:
        value = normalized.get(field)
        if isinstance(value, str):
            try:
                normalized[field] = UUID(value) if value else None
            except ValueError as error:
                raise ValueError(f"{field} must be a UUID.") from error
    for key, value in normalized.items():
        if isinstance(value, str):
            normalized[key] = value.strip() or None
    return normalized


def _require(values: dict[str, Any], required: tuple[str, ...]) -> None:
    missing = [field for field in required if values.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}.")


def _apply_changes(existing: Any, payload: dict[str, Any]) -> Any:
    allowed = {item.name for item in fields(existing)} - set(PROTECTED_FIELDS)
    changes = {key: value for key, value in payload.items() if key in allowed}
    return replace(existing, **changes, row_version=(existing.row_version or 0) + 1)


async def _ensure_employee(uow: GenUnitOfWork, employee_id: UUID | None, label: str) -> None:
    if employee_id is None:
        return
    repo = uow.get_repo(EmployeeEntity, EmployeeModel)
    if await repo.find_one(EmployeeModel.id == employee_id) is None:
        raise ValueError(f"{label} not found.")


async def _validate_assignment(uow: GenUnitOfWork, values: dict[str, Any]) -> None:
    _require(values, ("employee_id", "company_id", "employment_type", "employee_category", "hire_date", "effective_from"))

    operational_group = values.get("operational_group")
    if operational_group is not None and operational_group not in OPERATIONAL_GROUPS:
        raise ValueError(f"operational_group must be one of: {', '.join(OPERATIONAL_GROUPS)}.")

    effective_from, effective_to = values.get("effective_from"), values.get("effective_to")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("effective_to must be on or after effective_from.")

    separation_date, hire_date = values.get("separation_date"), values.get("hire_date")
    if separation_date is not None and separation_date < hire_date:
        raise ValueError("separation_date must be on or after hire_date.")

    if values.get("supervisor_employee_id") == values.get("employee_id"):
        raise ValueError("An employee cannot be their own supervisor.")

    await _ensure_employee(uow, values.get("employee_id"), "Employee")
    await _ensure_employee(uow, values.get("supervisor_employee_id"), "Supervisor employee")

    company_repo = uow.get_repo(CompanyEntity, CompanyModel)
    if await company_repo.find_one(CompanyModel.id == values["company_id"]) is None:
        raise ValueError("Company not found.")

    org_unit_id = values.get("org_unit_id")
    if org_unit_id is not None:
        org_unit_repo = uow.get_repo(OrgUnitEntity, OrgUnit)
        org_unit = await org_unit_repo.find_one(OrgUnit.id == org_unit_id)
        if org_unit is None:
            raise ValueError("Org unit not found.")
        if org_unit.company_id != values["company_id"]:
            raise ValueError("Org unit does not belong to the selected company.")

    primary_location_id = values.get("primary_location_id")
    if primary_location_id is not None:
        location_repo = uow.get_repo(LocationEntity, Location)
        location = await location_repo.find_one(Location.id == primary_location_id)
        if location is None or location.company_id != values["company_id"]:
            raise ValueError("Primary location does not belong to the selected company.")

    payroll_group_id = values.get("payroll_group_id")
    if payroll_group_id is not None:
        payroll_group_repo = uow.get_repo(PayrollGroupEntity, PayrollGroupModel)
        payroll_group = await payroll_group_repo.find_one(
            PayrollGroupModel.id == payroll_group_id
        )
        if payroll_group is None:
            raise ValueError("Payroll group not found.")
        if payroll_group.company_id != values["company_id"]:
            raise ValueError("Payroll group does not belong to the selected company.")


async def _validate_skill(uow: GenUnitOfWork, values: dict[str, Any], skill_id: UUID | None = None) -> None:
    _require(values, ("employee_id", "skill_code"))

    issued_date, expiry_date = values.get("issued_date"), values.get("expiry_date")
    if issued_date is not None and expiry_date is not None and expiry_date < issued_date:
        raise ValueError("expiry_date must be on or after issued_date.")

    await _ensure_employee(uow, values.get("employee_id"), "Employee")
    await _ensure_employee(uow, values.get("verified_by"), "Verifying employee")

    repo = uow.get_repo(EmployeeSkillEntity, EmployeeSkillModel)
    criteria = [
        EmployeeSkillModel.employee_id == values["employee_id"],
        EmployeeSkillModel.skill_code == values["skill_code"],
        EmployeeSkillModel.certification_no.is_not_distinct_from(values.get("certification_no")),
    ]
    if skill_id is not None:
        criteria.append(EmployeeSkillModel.id != skill_id)
    if await repo.find_all(*criteria, limit=1):
        raise ValueError("This skill and certification number already exist for the employee.")


class CreateEmploymentAssignmentUseCase(BaseUseCase[EmploymentAssignmentEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> EmploymentAssignmentEntity:
        async with self.uow as uow:
            values = _normalize(payload, ASSIGNMENT_DATE_FIELDS, ASSIGNMENT_UUID_FIELDS)
            values.pop("id", None)
            await _validate_assignment(uow, values)
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            return await repo.add(values)


class UpdateEmploymentAssignmentUseCase(BaseUseCase[EmploymentAssignmentEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, assignment_id: UUID, payload: dict[str, Any]) -> EmploymentAssignmentEntity:
        async with self.uow as uow:
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            existing = await repo.find_one(EmploymentAssignmentModel.id == assignment_id)
            if existing is None:
                raise ValueError("Employment assignment not found.")
            updated = _apply_changes(existing, _normalize(payload, ASSIGNMENT_DATE_FIELDS, ASSIGNMENT_UUID_FIELDS))
            await _validate_assignment(uow, updated.__dict__)
            return await repo.update(updated)


class GetEmploymentAssignmentUseCase(BaseUseCase[EmploymentAssignmentEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, assignment_id: UUID) -> EmploymentAssignmentEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            return await repo.find_one(EmploymentAssignmentModel.id == assignment_id)


class ListEmploymentAssignmentsUseCase(BaseUseCase[list[EmploymentAssignmentEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, employee_id: UUID | None = None) -> list[EmploymentAssignmentEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            criteria = [EmploymentAssignmentModel.employee_id == employee_id] if employee_id else []
            return await repo.find_all(
                *criteria,
                order_by=EmploymentAssignmentModel.effective_from.desc(),
                offset=0,
                limit=1000,
            )


class CreateEmployeeSkillUseCase(BaseUseCase[EmployeeSkillEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> EmployeeSkillEntity:
        async with self.uow as uow:
            values = _normalize(payload, SKILL_DATE_FIELDS, SKILL_UUID_FIELDS)
            values.pop("id", None)
            await _validate_skill(uow, values)
            repo = uow.get_repo(EmployeeSkillEntity, EmployeeSkillModel)
            return await repo.add(values)


class UpdateEmployeeSkillUseCase(BaseUseCase[EmployeeSkillEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, skill_id: UUID, payload: dict[str, Any]) -> EmployeeSkillEntity:
        async with self.uow as uow:
            repo = uow.get_repo(EmployeeSkillEntity, EmployeeSkillModel)
            existing = await repo.find_one(EmployeeSkillModel.id == skill_id)
            if existing is None:
                raise ValueError("Employee skill not found.")
            updated = _apply_changes(existing, _normalize(payload, SKILL_DATE_FIELDS, SKILL_UUID_FIELDS))
            await _validate_skill(uow, updated.__dict__, skill_id)
            return await repo.update(updated)


class GetEmployeeSkillUseCase(BaseUseCase[EmployeeSkillEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, skill_id: UUID) -> EmployeeSkillEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(EmployeeSkillEntity, EmployeeSkillModel)
            return await repo.find_one(EmployeeSkillModel.id == skill_id)


class ListEmployeeSkillsUseCase(BaseUseCase[list[EmployeeSkillEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, employee_id: UUID | None = None) -> list[EmployeeSkillEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(EmployeeSkillEntity, EmployeeSkillModel)
            criteria = [EmployeeSkillModel.employee_id == employee_id] if employee_id else []
            return await repo.find_all(
                *criteria,
                order_by=EmployeeSkillModel.skill_code,
                offset=0,
                limit=1000,
            )
