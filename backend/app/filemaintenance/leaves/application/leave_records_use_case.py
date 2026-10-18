from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.generics.mapper import GenericMapper
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.leaves.domain.entities.leave_records import (
    EmployeeEntitlementEntity,
    LeaveApplicationDateEntity,
    LeaveApplicationEntity,
    LeaveLedgerEntity,
)
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (
    EmployeeEntitlementModel,
    LeaveApplicationDateModel,
    LeaveApplicationModel,
    LeaveLedgerModel,
)
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    require_employee_phase_open,
)

EntityT = TypeVar("EntityT")
ModelT = TypeVar("ModelT")
BALANCE_FIELDS = (
    "opening_minutes",
    "granted_minutes",
    "accrued_minutes",
    "carryover_minutes",
    "adjustment_minutes",
    "used_minutes",
    "reserved_minutes",
    "expired_minutes",
    "converted_minutes",
)


def calculate_available_minutes(values: dict[str, Any]) -> int:
    return (
        int(values.get("opening_minutes", 0))
        + int(values.get("granted_minutes", 0))
        + int(values.get("accrued_minutes", 0))
        + int(values.get("carryover_minutes", 0))
        + int(values.get("adjustment_minutes", 0))
        - int(values.get("used_minutes", 0))
        - int(values.get("reserved_minutes", 0))
        - int(values.get("expired_minutes", 0))
        - int(values.get("converted_minutes", 0))
    )


def approved_leave_charge_minutes(requested_minutes: int, available_minutes: int) -> int:
    return min(requested_minutes, max(available_minutes, 0))


async def _validate_leave_type_company(
    session: Any,
    employee_id: UUID,
    leave_type_id: UUID,
    leave_date: date,
) -> None:
    leave_type = await session.get(LeaveTypeModel, leave_type_id)
    if leave_type is None:
        raise ValueError("The selected leave type was not found.")
    assigned_companies = await session.scalars(
        select(EmploymentAssignmentModel.company_id).where(
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= leave_date,
            EmploymentAssignmentModel.effective_to.is_(None)
            | (EmploymentAssignmentModel.effective_to >= leave_date),
            EmploymentAssignmentModel.separation_date.is_(None)
            | (EmploymentAssignmentModel.separation_date >= leave_date),
        )
    )
    if leave_type.company_id not in set(assigned_companies.all()):
        raise ValueError("The selected leave type does not belong to one of the employee's assigned companies.")


def _with_calculated_balance(entity: EmployeeEntitlementEntity) -> EmployeeEntitlementEntity:
    return replace(entity, available_minutes=calculate_available_minutes(entity.__dict__))


async def _validate_entitlement_grant(
    session: Any,
    employee_id: UUID,
    leave_type_id: UUID,
    today: date,
) -> None:
    assignment_result = await session.execute(
        select(EmploymentAssignmentModel)
        .where(
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.primary_location_id.is_not(None),
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            (EmploymentAssignmentModel.effective_to.is_(None) | (EmploymentAssignmentModel.effective_to >= today)),
            (EmploymentAssignmentModel.separation_date.is_(None) | (EmploymentAssignmentModel.separation_date >= today)),
        )
        .order_by(EmploymentAssignmentModel.effective_from.desc())
        .limit(1)
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        raise ValueError("The employee has no active employment assignment.")

    leave_type_result = await session.execute(
        select(LeaveTypeModel).where(LeaveTypeModel.id == leave_type_id)
    )
    leave_type = leave_type_result.scalar_one_or_none()
    if leave_type is None or leave_type.company_id != assignment.company_id:
        raise ValueError("The leave type does not belong to the employee's assigned company.")
    if (
        not leave_type.is_active
        or leave_type.status != "ACTIVE"
        or leave_type.effective_from > today
        or (leave_type.effective_to is not None and leave_type.effective_to < today)
    ):
        raise ValueError("The leave type is not currently active.")

    hire_date = assignment.hire_date
    service_months = (today.year - hire_date.year) * 12 + today.month - hire_date.month
    if today.day < hire_date.day:
        service_months -= 1
    service_months = max(0, service_months)
    if service_months < leave_type.minimum_service_months:
        raise ValueError(
            f"Employee has completed {service_months} of "
            f"{leave_type.minimum_service_months} required service months."
        )


async def _post_approved_leave_charge(session: Any, application: LeaveApplicationModel, actor_id: UUID) -> None:
    ledger_result = await session.execute(
        select(LeaveLedgerModel.id)
        .where(
            LeaveLedgerModel.reference_type == "LEAVE_APPLICATION",
            LeaveLedgerModel.reference_id == application.id,
            LeaveLedgerModel.transaction_type == "LEAVE_USED",
        )
        .limit(1)
    )
    if ledger_result.scalar_one_or_none() is not None:
        return

    entitlement_year = application.start_at.astimezone(ZoneInfo("Asia/Manila")).year
    entitlement_result = await session.execute(
        select(EmployeeEntitlementModel)
        .where(
            EmployeeEntitlementModel.employee_id == application.employee_id,
            EmployeeEntitlementModel.leave_type_id == application.leave_type_id,
            EmployeeEntitlementModel.entitlement_year == entitlement_year,
        )
        .with_for_update()
    )
    entitlement = entitlement_result.scalar_one_or_none()
    if entitlement is None:
        raise ValueError(
            "Cannot approve this leave: no matching employee entitlement exists for "
            f"employee {application.employee_id}, leave type {application.leave_type_id}, "
            f"and entitlement year {entitlement_year}. The entitlement must reference "
            "the exact leave type record used by this application."
        )

    available_minutes = calculate_available_minutes(
        {field: getattr(entitlement, field) for field in BALANCE_FIELDS}
    )
    charged_minutes = approved_leave_charge_minutes(
        application.requested_minutes,
        available_minutes,
    )
    application.paid_minutes = charged_minutes
    application.unpaid_minutes = application.requested_minutes - charged_minutes

    now = datetime.now(timezone.utc)
    entitlement.used_minutes += charged_minutes
    entitlement.available_minutes = calculate_available_minutes(
        {field: getattr(entitlement, field) for field in BALANCE_FIELDS}
    )
    entitlement.last_calculated_at = now
    if charged_minutes:
        session.add(
            LeaveLedgerModel(
                employee_id=application.employee_id,
                leave_type_id=application.leave_type_id,
                transaction_date=application.start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
                transaction_type="LEAVE_USED",
                reference_type="LEAVE_APPLICATION",
                reference_id=application.id,
                minutes_delta=-charged_minutes,
                balance_after_minutes=entitlement.available_minutes,
                remarks=f"Approved leave application {application.application_no}",
                posted_by=actor_id,
            )
        )


def _to_entity(model: Any, entity_type: type[EntityT]) -> EntityT:
    return GenericMapper.to_entity(model, entity_type)


async def _create(
    uow: GenUnitOfWork,
    model_type: type[ModelT],
    entity_type: type[EntityT],
    values: dict[str, Any],
) -> EntityT:
    async with uow as active_uow:
        model = model_type(**values)
        active_uow.session.add(model)
        await active_uow.session.flush()
        await active_uow.session.refresh(model)
        return _to_entity(model, entity_type)


async def _get(
    uow: GenUnitOfWork,
    model_type: type[ModelT],
    entity_type: type[EntityT],
    record_id: UUID,
) -> EntityT | None:
    async with uow as active_uow:
        result = await active_uow.session.execute(
            select(model_type).where(model_type.id == record_id)
        )
        model = result.scalar_one_or_none()
        return _to_entity(model, entity_type) if model is not None else None


async def _list(
    uow: GenUnitOfWork,
    model_type: type[ModelT],
    entity_type: type[EntityT],
    criteria: list[Any],
    order_by: Any,
    offset: int,
    limit: int,
) -> list[EntityT]:
    async with uow as active_uow:
        order_values = order_by if isinstance(order_by, (list, tuple)) else (order_by,)
        statement = (
            select(model_type)
            .where(*criteria)
            .order_by(*order_values)
            .offset(offset)
            .limit(limit)
        )
        result = await active_uow.session.execute(statement)
        return [_to_entity(model, entity_type) for model in result.scalars().all()]


async def _update(
    uow: GenUnitOfWork,
    model_type: type[ModelT],
    entity_type: type[EntityT],
    record_id: UUID,
    values: dict[str, Any],
) -> EntityT | None:
    async with uow as active_uow:
        result = await active_uow.session.execute(
            select(model_type).where(model_type.id == record_id).with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        for key, value in values.items():
            setattr(model, key, value)
        if hasattr(model, "row_version"):
            model.row_version += 1
        if hasattr(model, "updated_at"):
            model.updated_at = datetime.now(timezone.utc)
        await active_uow.session.flush()
        await active_uow.session.refresh(model)
        return _to_entity(model, entity_type)


class EmployeeEntitlementUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def create(self, values: dict[str, Any]) -> EmployeeEntitlementEntity:
        async with self.uow as active_uow:
            today = datetime.now(ZoneInfo("Asia/Manila")).date()
            await _validate_entitlement_grant(
                active_uow.session,
                values["employee_id"],
                values["leave_type_id"],
                today,
            )
            normalized = {
                **values,
                "available_minutes": calculate_available_minutes(values),
            }
            model = EmployeeEntitlementModel(**normalized)
            active_uow.session.add(model)
            await active_uow.session.flush()
            await active_uow.session.refresh(model)
            return _to_entity(model, EmployeeEntitlementEntity)

    async def get(self, record_id: UUID) -> EmployeeEntitlementEntity | None:
        entity = await _get(self.uow, EmployeeEntitlementModel, EmployeeEntitlementEntity, record_id)
        return _with_calculated_balance(entity) if entity is not None else None

    async def list(
        self,
        employee_id: UUID | None,
        leave_type_id: UUID | None,
        entitlement_year: int | None,
        offset: int,
        limit: int,
    ) -> list[EmployeeEntitlementEntity]:
        criteria = []
        if employee_id is not None:
            criteria.append(EmployeeEntitlementModel.employee_id == employee_id)
        if leave_type_id is not None:
            criteria.append(EmployeeEntitlementModel.leave_type_id == leave_type_id)
        if entitlement_year is not None:
            criteria.append(EmployeeEntitlementModel.entitlement_year == entitlement_year)
        result = await _list(
            self.uow,
            EmployeeEntitlementModel,
            EmployeeEntitlementEntity,
            criteria,
            (EmployeeEntitlementModel.entitlement_year.desc(), EmployeeEntitlementModel.employee_id),
            offset,
            limit,
        )
        return [_with_calculated_balance(item) for item in result]

    async def update(self, record_id: UUID, values: dict[str, Any]) -> EmployeeEntitlementEntity | None:
        async with self.uow as active_uow:
            result = await active_uow.session.execute(
                select(EmployeeEntitlementModel)
                .where(EmployeeEntitlementModel.id == record_id)
                .with_for_update()
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            next_employee_id = values.get("employee_id", model.employee_id)
            next_leave_type_id = values.get("leave_type_id", model.leave_type_id)
            await _validate_entitlement_grant(
                active_uow.session,
                next_employee_id,
                next_leave_type_id,
                datetime.now(ZoneInfo("Asia/Manila")).date(),
            )
            balance_values = {field: getattr(model, field) for field in BALANCE_FIELDS}
            balance_values.update(values)
            values = {
                **values,
                "available_minutes": calculate_available_minutes(balance_values),
            }
            for key, value in values.items():
                setattr(model, key, value)
            if hasattr(model, "row_version"):
                model.row_version += 1
            if hasattr(model, "updated_at"):
                model.updated_at = datetime.now(timezone.utc)
            await active_uow.session.flush()
            await active_uow.session.refresh(model)
            return _with_calculated_balance(_to_entity(model, EmployeeEntitlementEntity))


class LeaveApplicationUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def create(self, values: dict[str, Any]) -> LeaveApplicationEntity:
        local_start = values["start_at"].astimezone(ZoneInfo("Asia/Manila"))
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            await _validate_leave_type_company(
                session,
                values["employee_id"],
                values["leave_type_id"],
                local_start.date(),
            )
            model = LeaveApplicationModel(**values)
            session.add(model)
            await session.flush()
            await session.refresh(model)
            return _to_entity(model, LeaveApplicationEntity)

    async def get(self, record_id: UUID) -> LeaveApplicationEntity | None:
        return await _get(self.uow, LeaveApplicationModel, LeaveApplicationEntity, record_id)

    async def submit_draft_for_approval(
        self,
        record_id: UUID,
        actor_id: UUID,
    ) -> LeaveApplicationEntity | None:
        async with self.uow as active_uow:
            result = await active_uow.session.execute(
                select(LeaveApplicationModel)
                .where(LeaveApplicationModel.id == record_id)
                .with_for_update()
            )
            model = result.scalar_one_or_none()
            if model is None or not model.is_active:
                return None
            if model.status != "DRAFT":
                raise ValueError("Only draft leave applications can be submitted for approval.")
            await require_employee_phase_open(
                active_uow.session,
                model.employee_id,
                model.start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
                model.end_at.astimezone(ZoneInfo("Asia/Manila")).date(),
                "EMPLOYEE",
                datetime.now(timezone.utc),
            )
            await _validate_leave_type_company(
                active_uow.session,
                model.employee_id,
                model.leave_type_id,
                model.start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
            )

            now = datetime.now(timezone.utc)
            model.status = "PENDING"
            model.submitted_at = now
            model.updated_by = actor_id
            model.updated_at = now
            model.row_version += 1
            await active_uow.session.flush()
            await active_uow.session.refresh(model)
            return _to_entity(model, LeaveApplicationEntity)

    async def list(
        self,
        employee_id: UUID | None,
        leave_type_id: UUID | None,
        application_status: str | None,
        offset: int,
        limit: int,
    ) -> list[LeaveApplicationEntity]:
        criteria = []
        if employee_id is not None:
            criteria.append(LeaveApplicationModel.employee_id == employee_id)
        if leave_type_id is not None:
            criteria.append(LeaveApplicationModel.leave_type_id == leave_type_id)
        if application_status is not None:
            criteria.append(LeaveApplicationModel.status == application_status)
        return await _list(
            self.uow,
            LeaveApplicationModel,
            LeaveApplicationEntity,
            criteria,
            LeaveApplicationModel.start_at.desc(),
            offset,
            limit,
        )

    async def list_pending_for_supervisor(
        self,
        supervisor_employee_id: UUID,
        as_of: date,
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                LeaveApplicationModel.id,
                LeaveApplicationModel.application_no,
                LeaveApplicationModel.employee_id,
                EmployeeModel.employee_no,
                EmployeeModel.first_name,
                EmployeeModel.middle_name,
                EmployeeModel.last_name,
                EmployeeModel.suffix,
                EmployeeModel.preferred_name,
                LeaveApplicationModel.leave_type_id,
                LeaveTypeModel.leave_name,
                LeaveTypeModel.unit_type,
                LeaveApplicationModel.start_at,
                LeaveApplicationModel.end_at,
                LeaveApplicationModel.requested_minutes,
                LeaveApplicationModel.reason,
                LeaveApplicationModel.created_at,
                LeaveApplicationModel.status,
            )
            .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
            .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
            .join(
                EmploymentAssignmentModel,
                EmploymentAssignmentModel.employee_id == LeaveApplicationModel.employee_id,
            )
            .where(
                EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= as_of,
                (EmploymentAssignmentModel.effective_to.is_(None))
                | (EmploymentAssignmentModel.effective_to >= as_of),
                (EmploymentAssignmentModel.separation_date.is_(None))
                | (EmploymentAssignmentModel.separation_date >= as_of),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
                LeaveApplicationModel.status == "PENDING",
                LeaveApplicationModel.is_active.is_(True),
            )
            .distinct()
            .order_by(LeaveApplicationModel.created_at.desc(), LeaveApplicationModel.id.desc())
        )
        async with self.uow as active_uow:
            result = await active_uow.session.execute(statement)
            pending_applications = []
            for row in result:
                employee_name = row.preferred_name or " ".join(
                    part for part in (row.first_name, row.middle_name, row.last_name, row.suffix) if part
                )
                pending_applications.append(
                    {
                        "id": row.id,
                        "application_no": row.application_no,
                        "employee_id": row.employee_id,
                        "employee_no": row.employee_no,
                        "employee_name": employee_name,
                        "leave_type_id": row.leave_type_id,
                        "leave_type_name": row.leave_name,
                        "unit_type": row.unit_type,
                        "start_at": row.start_at,
                        "end_at": row.end_at,
                        "requested_minutes": row.requested_minutes,
                        "reason": row.reason,
                        "created_at": row.created_at,
                        "status": row.status,
                    }
                )
            return pending_applications

    async def count_pending_for_supervisor(
        self,
        supervisor_employee_id: UUID,
        as_of: date,
    ) -> int:
        statement = (
            select(func.count(func.distinct(LeaveApplicationModel.id)))
            .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
            .join(
                EmploymentAssignmentModel,
                EmploymentAssignmentModel.employee_id == LeaveApplicationModel.employee_id,
            )
            .where(
                EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= as_of,
                (EmploymentAssignmentModel.effective_to.is_(None))
                | (EmploymentAssignmentModel.effective_to >= as_of),
                (EmploymentAssignmentModel.separation_date.is_(None))
                | (EmploymentAssignmentModel.separation_date >= as_of),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
                LeaveApplicationModel.status == "PENDING",
                LeaveApplicationModel.is_active.is_(True),
            )
        )
        async with self.uow as active_uow:
            result = await active_uow.session.execute(statement)
            return int(result.scalar_one())

    async def decide_pending_for_supervisor(
        self,
        supervisor_employee_id: UUID,
        application_id: UUID,
        decision: str,
        actor_id: UUID,
        as_of: date,
    ) -> LeaveApplicationEntity | None:
        statement = (
            select(LeaveApplicationModel)
            .join(
                EmploymentAssignmentModel,
                EmploymentAssignmentModel.employee_id == LeaveApplicationModel.employee_id,
            )
            .where(
                LeaveApplicationModel.id == application_id,
                LeaveApplicationModel.status == "PENDING",
                LeaveApplicationModel.is_active.is_(True),
                EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= as_of,
                (EmploymentAssignmentModel.effective_to.is_(None))
                | (EmploymentAssignmentModel.effective_to >= as_of),
                (EmploymentAssignmentModel.separation_date.is_(None))
                | (EmploymentAssignmentModel.separation_date >= as_of),
            )
            .with_for_update(of=LeaveApplicationModel)
        )
        async with self.uow as active_uow:
            result = await active_uow.session.execute(statement)
            model = result.scalars().first()
            if model is None:
                return None
            await require_employee_phase_open(
                active_uow.session,
                model.employee_id,
                model.start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
                model.end_at.astimezone(ZoneInfo("Asia/Manila")).date(),
                "SUPERVISOR",
                datetime.now(timezone.utc),
            )
            now = datetime.now(timezone.utc)
            if decision == "APPROVED":
                await _post_approved_leave_charge(active_uow.session, model, actor_id)
            model.status = decision
            model.approved_at = now if decision == "APPROVED" else None
            model.updated_by = actor_id
            model.updated_at = now
            model.row_version += 1
            await active_uow.session.flush()
            await active_uow.session.refresh(model)
            return _to_entity(model, LeaveApplicationEntity)

    async def update_with_approval_posting(
        self,
        record_id: UUID,
        values: dict[str, Any],
        actor_id: UUID,
    ) -> LeaveApplicationEntity | None:
        async with self.uow as active_uow:
            result = await active_uow.session.execute(
                select(LeaveApplicationModel)
                .where(LeaveApplicationModel.id == record_id)
                .with_for_update()
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None

            next_status = values.get("status", model.status)
            next_employee_id = values.get("employee_id", model.employee_id)
            next_leave_type_id = values.get("leave_type_id", model.leave_type_id)
            next_start_at = values.get("start_at", model.start_at)
            await _validate_leave_type_company(
                active_uow.session,
                next_employee_id,
                next_leave_type_id,
                next_start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
            )
            was_approved = model.status == "APPROVED"
            if was_approved and next_status != "APPROVED":
                raise ValueError("An approved leave application cannot be moved back to another status.")
            if was_approved and {
                "employee_id",
                "leave_type_id",
                "start_at",
                "requested_minutes",
                "paid_minutes",
                "unpaid_minutes",
            }.intersection(values):
                raise ValueError("The leave entitlement charge cannot be changed after approval.")

            for key, value in values.items():
                setattr(model, key, value)
            if next_status == "APPROVED" and not was_approved:
                await _post_approved_leave_charge(active_uow.session, model, actor_id)
            if hasattr(model, "row_version"):
                model.row_version += 1
            if hasattr(model, "updated_at"):
                model.updated_at = datetime.now(timezone.utc)
            await active_uow.session.flush()
            await active_uow.session.refresh(model)
            return _to_entity(model, LeaveApplicationEntity)

    async def update(self, record_id: UUID, values: dict[str, Any]) -> LeaveApplicationEntity | None:
        return await _update(self.uow, LeaveApplicationModel, LeaveApplicationEntity, record_id, values)


class LeaveApplicationDateUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def create(self, values: dict[str, Any]) -> LeaveApplicationDateEntity:
        return await _create(self.uow, LeaveApplicationDateModel, LeaveApplicationDateEntity, values)

    async def get(self, record_id: UUID) -> LeaveApplicationDateEntity | None:
        return await _get(self.uow, LeaveApplicationDateModel, LeaveApplicationDateEntity, record_id)

    async def list(
        self,
        application_id: UUID,
        offset: int,
        limit: int,
    ) -> list[LeaveApplicationDateEntity]:
        return await _list(
            self.uow,
            LeaveApplicationDateModel,
            LeaveApplicationDateEntity,
            [LeaveApplicationDateModel.leave_application_id == application_id],
            LeaveApplicationDateModel.leave_date,
            offset,
            limit,
        )

    async def update(
        self,
        record_id: UUID,
        values: dict[str, Any],
    ) -> LeaveApplicationDateEntity | None:
        return await _update(
            self.uow, LeaveApplicationDateModel, LeaveApplicationDateEntity, record_id, values
        )

    async def delete(self, record_id: UUID) -> bool:
        async with self.uow as active_uow:
            result = await active_uow.session.execute(
                select(LeaveApplicationDateModel)
                .where(LeaveApplicationDateModel.id == record_id)
                .with_for_update()
            )
            model = result.scalar_one_or_none()
            if model is None:
                return False
            await active_uow.session.delete(model)
            await active_uow.session.flush()
            return True


class LeaveLedgerUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def create(self, values: dict[str, Any]) -> LeaveLedgerEntity:
        return await _create(self.uow, LeaveLedgerModel, LeaveLedgerEntity, values)

    async def get(self, record_id: UUID) -> LeaveLedgerEntity | None:
        return await _get(self.uow, LeaveLedgerModel, LeaveLedgerEntity, record_id)

    async def list(
        self,
        employee_id: UUID | None,
        leave_type_id: UUID | None,
        transaction_date_from: date | None,
        transaction_date_to: date | None,
        offset: int,
        limit: int,
    ) -> list[LeaveLedgerEntity]:
        criteria = []
        if employee_id is not None:
            criteria.append(LeaveLedgerModel.employee_id == employee_id)
        if leave_type_id is not None:
            criteria.append(LeaveLedgerModel.leave_type_id == leave_type_id)
        if transaction_date_from is not None:
            criteria.append(LeaveLedgerModel.transaction_date >= transaction_date_from)
        if transaction_date_to is not None:
            criteria.append(LeaveLedgerModel.transaction_date <= transaction_date_to)
        return await _list(
            self.uow,
            LeaveLedgerModel,
            LeaveLedgerEntity,
            criteria,
            (LeaveLedgerModel.transaction_date.desc(), LeaveLedgerModel.posted_at.desc()),
            offset,
            limit,
        )
