from dataclasses import fields, replace
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

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
    EmploymentAssignmentGeofenceModel,
    EmploymentAssignmentLocationModel,
)
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
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


def _normalize_assignment(payload: dict[str, Any]) -> dict[str, Any]:
    values = _normalize(payload, ASSIGNMENT_DATE_FIELDS, ASSIGNMENT_UUID_FIELDS)
    if "location_ids" in values:
        try:
            values["location_ids"] = [UUID(str(item)) for item in (values["location_ids"] or [])]
        except (TypeError, ValueError) as error:
            raise ValueError("location_ids must contain valid UUIDs.") from error
    if "authorized_geofence_ids" in values:
        try:
            values["authorized_geofence_ids"] = [
                UUID(str(item)) for item in (values["authorized_geofence_ids"] or [])
            ]
        except (TypeError, ValueError) as error:
            raise ValueError("authorized_geofence_ids must contain valid UUIDs.") from error
    return values


async def _get_assignment_geofence_ids(uow: GenUnitOfWork, assignment_id: UUID) -> list[UUID]:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return list((await uow.session.scalars(
        select(EmploymentAssignmentGeofenceModel.geofence_id)
        .where(EmploymentAssignmentGeofenceModel.assignment_id == assignment_id)
        .order_by(EmploymentAssignmentGeofenceModel.geofence_id)
    )).all())


async def _get_assignment_location_ids(uow: GenUnitOfWork, assignment_id: UUID) -> list[UUID]:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return list((await uow.session.scalars(
        select(EmploymentAssignmentLocationModel.location_id)
        .where(EmploymentAssignmentLocationModel.assignment_id == assignment_id)
        .order_by(EmploymentAssignmentLocationModel.location_id)
    )).all())


async def _get_assignment_geofence_ids_by_assignment(
    uow: GenUnitOfWork,
    assignment_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    if not assignment_ids:
        return {}
    rows = (await uow.session.execute(
        select(
            EmploymentAssignmentGeofenceModel.assignment_id,
            EmploymentAssignmentGeofenceModel.geofence_id,
        )
        .where(EmploymentAssignmentGeofenceModel.assignment_id.in_(assignment_ids))
        .order_by(EmploymentAssignmentGeofenceModel.geofence_id)
    )).all()
    result: dict[UUID, list[UUID]] = {}
    for assignment_id, geofence_id in rows:
        result.setdefault(assignment_id, []).append(geofence_id)
    return result


async def _get_assignment_location_ids_by_assignment(
    uow: GenUnitOfWork,
    assignment_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    if not assignment_ids:
        return {}
    rows = (await uow.session.execute(
        select(
            EmploymentAssignmentLocationModel.assignment_id,
            EmploymentAssignmentLocationModel.location_id,
        )
        .where(EmploymentAssignmentLocationModel.assignment_id.in_(assignment_ids))
        .order_by(EmploymentAssignmentLocationModel.location_id)
    )).all()
    result: dict[UUID, list[UUID]] = {}
    for assignment_id, location_id in rows:
        result.setdefault(assignment_id, []).append(location_id)
    return result


async def _replace_assignment_geofences(
    uow: GenUnitOfWork,
    assignment_id: UUID | None,
    company_id: UUID,
    geofence_ids: list[UUID],
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    if assignment_id is None:
        raise RuntimeError("Created employment assignment has no id.")
    await uow.session.execute(
        delete(EmploymentAssignmentGeofenceModel).where(
            EmploymentAssignmentGeofenceModel.assignment_id == assignment_id
        )
    )
    uow.session.add_all(
        EmploymentAssignmentGeofenceModel(
            assignment_id=assignment_id,
            company_id=company_id,
            geofence_id=geofence_id,
        )
        for geofence_id in geofence_ids
    )


async def _replace_assignment_locations(
    uow: GenUnitOfWork,
    assignment_id: UUID | None,
    company_id: UUID,
    location_ids: list[UUID],
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    if assignment_id is None:
        raise RuntimeError("Created employment assignment has no id.")
    await uow.session.execute(
        delete(EmploymentAssignmentLocationModel).where(
            EmploymentAssignmentLocationModel.assignment_id == assignment_id
        )
    )
    uow.session.add_all(
        EmploymentAssignmentLocationModel(
            assignment_id=assignment_id,
            company_id=company_id,
            location_id=location_id,
        )
        for location_id in location_ids
    )


async def _ensure_employee(uow: GenUnitOfWork, employee_id: UUID | None, label: str) -> None:
    if employee_id is None:
        return
    repo = uow.get_repo(EmployeeEntity, EmployeeModel)
    if await repo.find_one(EmployeeModel.id == employee_id) is None:
        raise ValueError(f"{label} not found.")


async def _lock_employee_assignment_scope(uow: GenUnitOfWork, employee_id: UUID) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    await uow.session.execute(
        select(EmployeeModel.id)
        .where(EmployeeModel.id == employee_id)
        .with_for_update()
    )


async def _ensure_single_active_assignment(
    uow: GenUnitOfWork,
    values: dict[str, Any],
    assignment_id: UUID | None = None,
) -> None:
    if values.get("status") != "ACTIVE" or not values.get("is_active", True):
        return
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")

    criteria = [
        EmploymentAssignmentModel.employee_id == values["employee_id"],
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.is_active.is_(True),
    ]
    if assignment_id is not None:
        criteria.append(EmploymentAssignmentModel.id != assignment_id)
    existing_id = await uow.session.scalar(
        select(EmploymentAssignmentModel.id).where(*criteria).limit(1)
    )
    if existing_id is not None:
        raise ValueError(
            "An employee can have only one active employment assignment. "
            "Deactivate the current assignment first."
        )


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

    authorized_geofence_ids = values.get("authorized_geofence_ids")
    authorized_geofence_ids = list(dict.fromkeys(authorized_geofence_ids or []))
    geofence_location_ids: set[UUID] = set()
    if authorized_geofence_ids:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        geofences = list((await uow.session.scalars(
            select(Geofence).where(
                Geofence.id.in_(authorized_geofence_ids),
                Geofence.company_id == values["company_id"],
            )
        )).all())
        geofences_by_id = {geofence.id: geofence for geofence in geofences}
        if (
            set(geofences_by_id) != set(authorized_geofence_ids)
            or any(geofence.company_id != values["company_id"] for geofence in geofences)
        ):
            raise ValueError("Authorized geofence does not belong to the selected company.")
        if any(geofence.location_id is None for geofence in geofences):
            raise ValueError("Every authorized geofence must be linked to a location.")
        location_repo = uow.get_repo(LocationEntity, Location)
        geofence_location_ids = {geofence.location_id for geofence in geofences}
        locations = await location_repo.find_all(
            Location.id.in_(geofence_location_ids),
            Location.company_id == values["company_id"],
            limit=len(geofence_location_ids),
        )
        if (
            {location.id for location in locations} != geofence_location_ids
            or any(location.company_id != values["company_id"] for location in locations)
        ):
            raise ValueError("Authorized geofence location does not belong to the selected company.")
    values["authorized_geofence_ids"] = authorized_geofence_ids

    has_location_list = "location_ids" in values
    location_ids = list(dict.fromkeys(values.get("location_ids") or []))
    if not has_location_list:
        if authorized_geofence_ids:
            values["primary_location_id"] = geofences_by_id[authorized_geofence_ids[0]].location_id
        primary_location_id = values.get("primary_location_id")
        location_ids = list(dict.fromkeys(
            ([primary_location_id] if primary_location_id is not None else [])
            + list(geofence_location_ids)
        ))
    elif not geofence_location_ids.issubset(set(location_ids)):
        raise ValueError("Every authorized geofence must belong to an assigned location.")

    if location_ids:
        location_repo = uow.get_repo(LocationEntity, Location)
        locations = await location_repo.find_all(
            Location.id.in_(location_ids),
            Location.company_id == values["company_id"],
            limit=len(location_ids),
        )
        if {location.id for location in locations} != set(location_ids):
            raise ValueError("Assigned location does not belong to the selected company.")
    values["location_ids"] = location_ids
    primary_location_id = values.get("primary_location_id")
    if primary_location_id not in location_ids:
        values["primary_location_id"] = location_ids[0] if location_ids else None
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
            values = _normalize_assignment(payload)
            values.pop("id", None)
            _require(values, ("employee_id",))
            await _lock_employee_assignment_scope(uow, values["employee_id"])
            await _ensure_single_active_assignment(uow, values)
            await _validate_assignment(uow, values)
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            result = await repo.add(values)
            await _replace_assignment_geofences(
                uow, result.id, values["company_id"], values.get("authorized_geofence_ids", [])
            )
            await _replace_assignment_locations(
                uow, result.id, values["company_id"], values.get("location_ids", [])
            )
            result.authorized_geofence_ids = values.get("authorized_geofence_ids", [])
            result.location_ids = values.get("location_ids", [])
            return result


class CreateEmploymentAssignmentsBatchUseCase(BaseUseCase[list[EmploymentAssignmentEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, rows: list[dict[str, Any]]) -> list[EmploymentAssignmentEntity]:
        if not rows or len(rows) > 500:
            raise ValueError("The batch must contain between 1 and 500 assignment rows.")

        async with self.uow as uow:
            prepared: list[tuple[int, dict[str, Any]]] = []
            seen_pairs: set[tuple[UUID, UUID]] = set()
            for row in rows:
                row_number = row.get("row_number")
                assignment = row.get("assignment")
                if not isinstance(row_number, int) or not isinstance(assignment, dict):
                    raise ValueError("Each batch row must include a row_number and assignment.")
                try:
                    values = _normalize_assignment(assignment)
                    values.pop("id", None)
                    _require(values, (
                        "employee_id",
                        "company_id",
                        "employment_type",
                        "employee_category",
                        "hire_date",
                        "effective_from",
                    ))
                    pair = (values["employee_id"], values["company_id"])
                    if pair in seen_pairs:
                        raise ValueError("The employee and company combination is duplicated in this file.")
                    seen_pairs.add(pair)
                except ValueError as error:
                    raise ValueError(f"CSV row {row_number}: {error}") from error
                prepared.append((row_number, values))

            employee_ids = sorted({values["employee_id"] for _, values in prepared})
            for employee_id in employee_ids:
                await _lock_employee_assignment_scope(uow, employee_id)

            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            company_ids = {values.get("company_id") for _, values in prepared}
            existing_pairs = set((await uow.session.execute(
                select(EmploymentAssignmentModel.employee_id, EmploymentAssignmentModel.company_id).where(
                    EmploymentAssignmentModel.employee_id.in_(employee_ids),
                    EmploymentAssignmentModel.company_id.in_(company_ids),
                )
            )).all())

            active_employees: set[UUID] = set()
            for row_number, values in prepared:
                try:
                    pair = (values["employee_id"], values["company_id"])
                    if pair in existing_pairs:
                        raise ValueError("An employment assignment already exists for this employee and company.")
                    is_active = values.get("is_active", True) and values.get("status", "ACTIVE") == "ACTIVE"
                    if is_active and values["employee_id"] in active_employees:
                        raise ValueError("An employee can have only one active employment assignment.")
                    if is_active:
                        active_employees.add(values["employee_id"])
                    await _ensure_single_active_assignment(uow, values)
                    await _validate_assignment(uow, values)
                except ValueError as error:
                    raise ValueError(f"CSV row {row_number}: {error}") from error

            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            created: list[EmploymentAssignmentEntity] = []
            for _, values in prepared:
                result = await repo.add(values)
                await _replace_assignment_geofences(
                    uow, result.id, values["company_id"], values.get("authorized_geofence_ids", [])
                )
                await _replace_assignment_locations(
                    uow, result.id, values["company_id"], values.get("location_ids", [])
                )
                result.authorized_geofence_ids = values.get("authorized_geofence_ids", [])
                result.location_ids = values.get("location_ids", [])
                created.append(result)
            return created


class UpdateEmploymentAssignmentUseCase(BaseUseCase[EmploymentAssignmentEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, assignment_id: UUID, payload: dict[str, Any]) -> EmploymentAssignmentEntity:
        async with self.uow as uow:
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            existing = await repo.find_one(EmploymentAssignmentModel.id == assignment_id)
            if existing is None:
                raise ValueError("Employment assignment not found.")
            existing.authorized_geofence_ids = await _get_assignment_geofence_ids(uow, assignment_id)
            existing.location_ids = await _get_assignment_location_ids(uow, assignment_id)
            normalized_payload = _normalize_assignment(payload)
            updated = _apply_changes(existing, normalized_payload)
            validation_values = updated.__dict__.copy()
            await _lock_employee_assignment_scope(uow, updated.employee_id)
            await _ensure_single_active_assignment(uow, validation_values, assignment_id)
            if "location_ids" not in normalized_payload:
                validation_values.pop("location_ids", None)
            await _validate_assignment(uow, validation_values)
            updated.location_ids = validation_values["location_ids"]
            updated.primary_location_id = validation_values["primary_location_id"]
            updated.authorized_geofence_ids = validation_values["authorized_geofence_ids"]
            result = await repo.update(updated)
            if "authorized_geofence_ids" in normalized_payload:
                await _replace_assignment_geofences(
                    uow,
                    assignment_id,
                    updated.company_id,
                    updated.authorized_geofence_ids or [],
                )
            if any(
                field in normalized_payload
                for field in ("location_ids", "primary_location_id", "authorized_geofence_ids")
            ):
                await _replace_assignment_locations(
                    uow,
                    assignment_id,
                    updated.company_id,
                    updated.location_ids or [],
                )
            result.authorized_geofence_ids = updated.authorized_geofence_ids or []
            result.location_ids = updated.location_ids or []
            return result


class GetEmploymentAssignmentUseCase(BaseUseCase[EmploymentAssignmentEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, assignment_id: UUID) -> EmploymentAssignmentEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            result = await repo.find_one(EmploymentAssignmentModel.id == assignment_id)
            if result is not None:
                result.authorized_geofence_ids = await _get_assignment_geofence_ids(uow, assignment_id)
                result.location_ids = await _get_assignment_location_ids(uow, assignment_id)
            return result


class ListEmploymentAssignmentsUseCase(BaseUseCase[list[EmploymentAssignmentEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        employee_id: UUID | None = None,
        company_id: UUID | None = None,
    ) -> list[EmploymentAssignmentEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(EmploymentAssignmentEntity, EmploymentAssignmentModel)
            criteria = []
            if employee_id:
                criteria.append(EmploymentAssignmentModel.employee_id == employee_id)
            if company_id:
                criteria.append(EmploymentAssignmentModel.company_id == company_id)
            assignments = await repo.find_all(
                *criteria,
                order_by=EmploymentAssignmentModel.effective_from.desc(),
                offset=0,
                limit=1000,
            )
            ids_by_assignment = await _get_assignment_geofence_ids_by_assignment(
                uow, [item.id for item in assignments if item.id is not None]
            )
            location_ids_by_assignment = await _get_assignment_location_ids_by_assignment(
                uow, [item.id for item in assignments if item.id is not None]
            )
            for assignment in assignments:
                assignment.authorized_geofence_ids = ids_by_assignment.get(assignment.id, [])
                assignment.location_ids = location_ids_by_assignment.get(assignment.id, [])
            return assignments


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
