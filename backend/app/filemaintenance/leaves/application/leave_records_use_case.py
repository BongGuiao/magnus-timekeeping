from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, delete, func, select
from app.auth.infrastructure.approval_routing import (
    approval_route_scope,
    assign_org_approval,
    legacy_supervisor_scope,
)
from app.auth.infrastructure.approval_routing_model import ApprovalRouteModel
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    DeadlineStage, require_attendance_open,
)

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
from app.filemaintenance.leaves.application.leave_duration import LeaveDuration, calculate_leave_duration

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


async def _validated_duration(
    session: Any, employee_id: UUID, start_at: datetime, end_at: datetime, requested_minutes: int,
) -> LeaveDuration:
    duration = await calculate_leave_duration(session, employee_id, start_at, end_at)
    if not duration.requested_minutes:
        raise ValueError("This period covers no scheduled work. No leave application is required.")
    if duration.requested_minutes != requested_minutes:
        raise ValueError(
            f"The scheduled leave duration is {duration.requested_minutes} minutes. "
            "Refresh the calculation and review the application."
        )
    return duration


async def _replace_draft_days(session: Any, application_id: UUID, duration: LeaveDuration) -> None:
    rows = list((await session.scalars(
        select(LeaveApplicationDateModel).where(
            LeaveApplicationDateModel.leave_application_id == application_id,
        ).with_for_update()
    )).all())
    if {row.leave_date: row.requested_minutes for row in rows} == {
        day.work_date: day.requested_minutes for day in duration.days
    }:
        return
    if any(
        row.roster_id is not None or row.approved_paid_minutes or row.approved_unpaid_minutes
        or row.attendance_overlap_minutes or row.final_charge_minutes or row.holiday_flag or row.rest_day_flag
        for row in rows
    ):
        raise ValueError("This draft has manually maintained leave-day details. Contact HR before changing its dates.")
    await session.execute(delete(LeaveApplicationDateModel).where(
        LeaveApplicationDateModel.leave_application_id == application_id,
    ))
    for day in duration.days:
        session.add(LeaveApplicationDateModel(
            leave_application_id=application_id, leave_date=day.work_date,
            requested_minutes=day.requested_minutes,
        ))


async def _verify_saved_days(session: Any, application: LeaveApplicationModel, duration: LeaveDuration):
    rows = list((await session.scalars(
        select(LeaveApplicationDateModel).where(
            LeaveApplicationDateModel.leave_application_id == application.id,
        ).with_for_update()
    )).all())
    expected = {day.work_date: day.requested_minutes for day in duration.days}
    if rows and {row.leave_date: row.requested_minutes for row in rows} != expected:
        raise ValueError("The scheduled leave dates changed. Contact HR and submit a new application.")
    return rows


async def _require_duration_open(session: Any, employee_id: UUID, duration: LeaveDuration, stage: DeadlineStage) -> None:
    await require_attendance_open(
        session, employee_id, duration.days[0].work_date, duration.days[-1].work_date, stage=stage,
    )


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


async def _lock_matching_entitlements(
    session: Any, employee_id: UUID, leave_type_id: UUID, start_year: int, end_year: int,
) -> None:
    # Serialize leave activity writes with deletion's entitlement row lock.
    await session.scalars(
        select(EmployeeEntitlementModel.id).where(
            EmployeeEntitlementModel.employee_id == employee_id,
            EmployeeEntitlementModel.leave_type_id == leave_type_id,
            EmployeeEntitlementModel.entitlement_year.between(start_year, end_year),
        ).order_by(EmployeeEntitlementModel.entitlement_year).with_for_update()
    )


def _entitlement_assignment_query(
    employee_ids: Collection[UUID],
    today: date,
) -> Select[tuple[EmploymentAssignmentModel]]:
    return (
        select(EmploymentAssignmentModel)
        .where(
            EmploymentAssignmentModel.employee_id.in_(employee_ids),
            EmploymentAssignmentModel.primary_location_id.is_not(None),
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            (EmploymentAssignmentModel.effective_to.is_(None) | (EmploymentAssignmentModel.effective_to >= today)),
            (EmploymentAssignmentModel.separation_date.is_(None) | (EmploymentAssignmentModel.separation_date >= today)),
        )
        .order_by(EmploymentAssignmentModel.employee_id, EmploymentAssignmentModel.effective_from.desc())
    )


async def _validate_entitlement_grant(
    session: Any,
    employee_id: UUID,
    leave_type_id: UUID,
    today: date,
) -> None:
    assignment_result = await session.execute(
        _entitlement_assignment_query([employee_id], today).limit(1)
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        raise ValueError("The employee has no active employment assignment.")

    leave_type_result = await session.execute(
        select(LeaveTypeModel).where(LeaveTypeModel.id == leave_type_id)
    )
    leave_type = leave_type_result.scalar_one_or_none()
    _validate_entitlement_grant_rules(assignment, leave_type, today)


def _validate_entitlement_grant_rules(
    assignment: EmploymentAssignmentModel,
    leave_type: LeaveTypeModel | None,
    today: date,
) -> None:
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
        select(func.coalesce(func.sum(LeaveLedgerModel.minutes_delta), 0))
        .where(
            LeaveLedgerModel.reference_type == "LEAVE_APPLICATION",
            LeaveLedgerModel.reference_id == application.id,
            LeaveLedgerModel.transaction_type.in_(("LEAVE_USED", "LEAVE_REVERSAL")),
        )
    )
    if ledger_result.scalar_one_or_none():
        raise ValueError("This application already has an outstanding leave charge. Contact HR.")

    duration = await _validated_duration(
        session, application.employee_id, application.start_at, application.end_at, application.requested_minutes,
    )
    await _require_duration_open(session, application.employee_id, duration, "APPROVAL")
    existing_days = await _verify_saved_days(session, application, duration)
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
    by_date = {row.leave_date: row for row in existing_days}
    remaining = charged_minutes
    for day in duration.days:
        paid = min(day.requested_minutes, remaining)
        remaining -= paid
        row = by_date.get(day.work_date)
        if row is None:
            row = LeaveApplicationDateModel(
                leave_application_id=application.id, leave_date=day.work_date,
                requested_minutes=day.requested_minutes,
            )
            session.add(row)
        row.approved_paid_minutes = paid
        row.approved_unpaid_minutes = day.requested_minutes - paid
        row.final_charge_minutes = paid

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

    async def delete(self, record_id: UUID) -> EmployeeEntitlementEntity | None:
        async with self.uow as active_uow:
            session = active_uow.session
            model = await session.scalar(
                select(EmployeeEntitlementModel)
                .where(EmployeeEntitlementModel.id == record_id)
                .with_for_update()
            )
            if model is None:
                return None
            year_start = datetime(model.entitlement_year, 1, 1, tzinfo=ZoneInfo("Asia/Manila"))
            year_end = datetime(model.entitlement_year + 1, 1, 1, tzinfo=ZoneInfo("Asia/Manila"))
            application = await session.scalar(select(LeaveApplicationModel.id).where(
                LeaveApplicationModel.employee_id == model.employee_id,
                LeaveApplicationModel.leave_type_id == model.leave_type_id,
                LeaveApplicationModel.start_at < year_end,
                LeaveApplicationModel.end_at > year_start,
            ).limit(1))
            ledger = await session.scalar(select(LeaveLedgerModel.id).where(
                LeaveLedgerModel.employee_id == model.employee_id,
                LeaveLedgerModel.leave_type_id == model.leave_type_id,
                LeaveLedgerModel.transaction_date >= year_start.date(),
                LeaveLedgerModel.transaction_date < year_end.date(),
            ).limit(1))
            if application is not None or ledger is not None or any(
                getattr(model, field) != 0
                for field in ("used_minutes", "reserved_minutes", "expired_minutes", "converted_minutes")
            ):
                raise ValueError("This entitlement cannot be deleted because it has leave activity.")
            entity = _with_calculated_balance(_to_entity(model, EmployeeEntitlementEntity))
            await session.delete(model)
            await session.flush()
            return entity


async def _require_leave_open(
    session: Any, employee_id: UUID, start_at: datetime, end_at: datetime,
    *, stage: DeadlineStage,
) -> None:
    await require_attendance_open(
        session, employee_id,
        start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
        (end_at - timedelta(microseconds=1)).astimezone(ZoneInfo("Asia/Manila")).date(),
        stage=stage,
    )


class LeaveApplicationUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def return_approved_to_pending(
        self, application_id: UUID, actor_id: UUID, actor_employee_id: UUID, reason: str,
        *, original_approver_only: bool = False,
    ) -> LeaveApplicationEntity | None:
        reason = reason.strip()
        if not reason:
            raise ValueError("A reason is required to return an approved leave application.")
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            application = (await session.execute(
                select(LeaveApplicationModel).where(LeaveApplicationModel.id == application_id).with_for_update()
            )).scalar_one_or_none()
            if application is None or not application.is_active:
                return None
            if application.employee_id == actor_employee_id:
                raise ValueError("You cannot return your own leave application.")
            if original_approver_only and application.approved_by_id != actor_id:
                raise ValueError("You can only return leave applications you personally approved.")
            if application.status != "APPROVED":
                raise ValueError("Only approved leave applications can be returned for approval.")
            if application.payroll_posted:
                raise ValueError("Payroll-posted leave cannot be returned for approval.")

            days = list((await session.scalars(
                select(LeaveApplicationDateModel)
                .where(LeaveApplicationDateModel.leave_application_id == application.id)
                .order_by(LeaveApplicationDateModel.leave_date)
                .with_for_update()
            )).all())
            start = application.start_at.astimezone(ZoneInfo("Asia/Manila")).date()
            end = (application.end_at - timedelta(microseconds=1)).astimezone(ZoneInfo("Asia/Manila")).date()
            if days:
                start = min(start, days[0].leave_date)
                end = max(end, days[-1].leave_date)
            await require_attendance_open(session, application.employee_id, start, end, stage="APPROVAL", lock_for_update=True)

            net = (await session.execute(
                select(func.coalesce(func.sum(LeaveLedgerModel.minutes_delta), 0)).where(
                    LeaveLedgerModel.reference_type == "LEAVE_APPLICATION",
                    LeaveLedgerModel.reference_id == application.id,
                    LeaveLedgerModel.transaction_type.in_(("LEAVE_USED", "LEAVE_REVERSAL")),
                )
            )).scalar_one()
            paid = application.paid_minutes or 0
            if net != -paid:
                raise ValueError("The leave charge and ledger do not match. Contact HR to review this application.")
            year = application.start_at.astimezone(ZoneInfo("Asia/Manila")).year
            entitlement = (await session.execute(
                select(EmployeeEntitlementModel).where(
                    EmployeeEntitlementModel.employee_id == application.employee_id,
                    EmployeeEntitlementModel.leave_type_id == application.leave_type_id,
                    EmployeeEntitlementModel.entitlement_year == year,
                ).with_for_update()
            )).scalar_one_or_none()
            if entitlement is None or entitlement.used_minutes < paid:
                raise ValueError("The matching leave entitlement cannot be safely restored. Contact HR.")

            await assign_org_approval(
                session, resource_type="leave_application", resource_id=application.id,
                employee_id=application.employee_id, assigned_by=actor_id,
                on_date=datetime.now(ZoneInfo("Asia/Manila")).date(),
                permission_code="leave.approve_team",
            )
            now = datetime.now(timezone.utc)
            entitlement.used_minutes -= paid
            entitlement.available_minutes = calculate_available_minutes(
                {field: getattr(entitlement, field) for field in BALANCE_FIELDS}
            )
            entitlement.last_calculated_at = now
            session.add(LeaveLedgerModel(
                employee_id=application.employee_id, leave_type_id=application.leave_type_id,
                transaction_date=application.start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
                transaction_type="LEAVE_REVERSAL", reference_type="LEAVE_APPLICATION",
                reference_id=application.id, minutes_delta=paid,
                balance_after_minutes=entitlement.available_minutes,
                remarks=f"Returned {application.application_no} for approval: {reason}", posted_by=actor_id,
            ))
            for day in days:
                day.approved_paid_minutes = 0
                day.approved_unpaid_minutes = 0
                day.final_charge_minutes = 0
            application.status = "PENDING"
            application.paid_minutes = None
            application.unpaid_minutes = None
            application.approved_at = None
            application.approved_by_id = None
            application.updated_by = actor_id
            application.updated_at = now
            application.row_version += 1
            await session.flush()
            await session.refresh(application)
            return _to_entity(application, LeaveApplicationEntity)

    async def create(self, values: dict[str, Any]) -> LeaveApplicationEntity:
        if values.get("status") in ("APPROVED", "REJECTED"):
            raise ValueError("Create a draft or pending leave application and use its approval workflow.")
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
            duration = await _validated_duration(
                session, values["employee_id"], values["start_at"], values["end_at"], values["requested_minutes"],
            )
            await _require_leave_open(
                session, values["employee_id"], values["start_at"], values["end_at"],
                stage="APPROVAL" if values.get("status") == "APPROVED" else "FILING",
            )
            await _require_duration_open(session, values["employee_id"], duration, "FILING")
            await _lock_matching_entitlements(
                session, values["employee_id"], values["leave_type_id"], local_start.year,
                (values["end_at"] - timedelta(microseconds=1)).astimezone(ZoneInfo("Asia/Manila")).year,
            )
            model = LeaveApplicationModel(**values)
            session.add(model)
            await session.flush()
            await _replace_draft_days(session, model.id, duration)
            if model.status == "PENDING":
                await assign_org_approval(
                    session,
                    resource_type="leave_application",
                    resource_id=model.id,
                    employee_id=model.employee_id,
                    assigned_by=values.get("created_by"),
                    on_date=datetime.now(ZoneInfo("Asia/Manila")).date(),
                    permission_code="leave.approve_team",
                    hold_unresolved=True,
                )
            await session.refresh(model)
            return _to_entity(model, LeaveApplicationEntity)

    async def get(self, record_id: UUID) -> LeaveApplicationEntity | None:
        return await _get(self.uow, LeaveApplicationModel, LeaveApplicationEntity, record_id)

    async def submit_draft_for_approval(
        self,
        record_id: UUID,
        actor_id: UUID,
        *,
        expected_employee_id: UUID | None = None,
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
            if expected_employee_id is not None and model.employee_id != expected_employee_id:
                raise ValueError("You can only submit your own leave application.")
            if model.status != "DRAFT":
                raise ValueError("Only draft leave applications can be submitted for approval.")
            await _require_leave_open(
                active_uow.session, model.employee_id, model.start_at, model.end_at,
                stage="FILING",
            )
            await _validate_leave_type_company(
                active_uow.session,
                model.employee_id,
                model.leave_type_id,
                model.start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
            )
            duration = await _validated_duration(
                active_uow.session, model.employee_id, model.start_at, model.end_at, model.requested_minutes,
            )
            await _require_duration_open(active_uow.session, model.employee_id, duration, "FILING")
            await _verify_saved_days(active_uow.session, model, duration)

            now = datetime.now(timezone.utc)
            await assign_org_approval(
                active_uow.session,
                resource_type="leave_application",
                resource_id=model.id,
                employee_id=model.employee_id,
                assigned_by=actor_id,
                on_date=now.astimezone(ZoneInfo("Asia/Manila")).date(),
                permission_code="leave.approve_team",
                hold_unresolved=True,
            )
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
            .where(
                approval_route_scope(
                    "leave_application",
                    LeaveApplicationModel.id,
                    supervisor_employee_id,
                    legacy_supervisor_scope(LeaveApplicationModel.employee_id, supervisor_employee_id, as_of),
                ),
                LeaveApplicationModel.employee_id != supervisor_employee_id,
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
            .where(
                approval_route_scope(
                    "leave_application",
                    LeaveApplicationModel.id,
                    supervisor_employee_id,
                    legacy_supervisor_scope(LeaveApplicationModel.employee_id, supervisor_employee_id, as_of),
                ),
                LeaveApplicationModel.employee_id != supervisor_employee_id,
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
            .where(
                LeaveApplicationModel.id == application_id,
                LeaveApplicationModel.status == "PENDING",
                LeaveApplicationModel.is_active.is_(True),
                LeaveApplicationModel.employee_id != supervisor_employee_id,
                approval_route_scope(
                    "leave_application",
                    LeaveApplicationModel.id,
                    supervisor_employee_id,
                    legacy_supervisor_scope(LeaveApplicationModel.employee_id, supervisor_employee_id, as_of),
                ),
            )
            .with_for_update(of=LeaveApplicationModel)
        )
        async with self.uow as active_uow:
            result = await active_uow.session.execute(statement)
            model = result.scalars().first()
            if model is None:
                return None
            await _require_leave_open(
                active_uow.session, model.employee_id, model.start_at, model.end_at,
                stage="APPROVAL",
            )
            now = datetime.now(timezone.utc)
            if decision == "APPROVED":
                await _post_approved_leave_charge(active_uow.session, model, actor_id)
            model.status = decision
            model.approved_at = now if decision == "APPROVED" else None
            model.approved_by_id = actor_id if decision == "APPROVED" else None
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
        actor_id: UUID | None,
        *,
        expected_employee_id: UUID | None = None,
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
            if expected_employee_id is not None and (
                model.employee_id != expected_employee_id or model.status != "DRAFT"
            ):
                raise ValueError("Only your own draft leave application can be changed.")

            next_status = values.get("status", model.status)
            next_employee_id = values.get("employee_id", model.employee_id)
            next_leave_type_id = values.get("leave_type_id", model.leave_type_id)
            next_start_at = values.get("start_at", model.start_at)
            route_mode = None
            if model.status == "PENDING":
                route_mode = await active_uow.session.scalar(
                    select(ApprovalRouteModel.routing_mode).where(
                        ApprovalRouteModel.resource_type == "leave_application",
                        ApprovalRouteModel.resource_id == model.id,
                        ApprovalRouteModel.is_current.is_(True),
                    )
                )
                if route_mode != "LEGACY" and next_employee_id != model.employee_id:
                    raise ValueError("The employee cannot be changed while an organization-routed leave is pending.")
            if (
                next_status in ("APPROVED", "REJECTED")
                and next_status != model.status
                and (model.status != "PENDING" or route_mode != "LEGACY")
            ):
                raise ValueError("Use the assigned approval workflow to approve or reject this leave application.")
            if next_status in ("APPROVED", "REJECTED") and next_status != model.status:
                if actor_id is None:
                    raise ValueError("An actor is required to approve or reject a leave application.")
                actor_employee_id = await active_uow.session.scalar(
                    select(UserModel.employee_id).where(UserModel.id == actor_id)
                )
                if actor_employee_id == next_employee_id:
                    raise ValueError("You cannot approve or reject your own leave application.")
            stage: DeadlineStage = (
                "APPROVAL"
                if next_status in ("APPROVED", "REJECTED") or model.status == "APPROVED"
                else "FILING"
            )
            await _require_leave_open(
                active_uow.session, model.employee_id, model.start_at, model.end_at,
                stage=stage,
            )
            await _require_leave_open(
                active_uow.session, next_employee_id, next_start_at,
                values.get("end_at", model.end_at), stage=stage,
            )
            await _validate_leave_type_company(
                active_uow.session,
                next_employee_id,
                next_leave_type_id,
                next_start_at.astimezone(ZoneInfo("Asia/Manila")).date(),
            )
            next_year = next_start_at.astimezone(ZoneInfo("Asia/Manila")).year
            next_end_at = values.get("end_at", model.end_at)
            duration = None
            if model.status == "DRAFT" and next_status == "DRAFT":
                duration = await _validated_duration(
                    active_uow.session, next_employee_id, next_start_at, next_end_at,
                    values.get("requested_minutes", model.requested_minutes),
                )
                await _require_duration_open(active_uow.session, next_employee_id, duration, "FILING")
            elif model.status == "DRAFT" and next_status == "PENDING":
                duration_to_submit = await _validated_duration(
                    active_uow.session, next_employee_id, next_start_at, next_end_at,
                    values.get("requested_minutes", model.requested_minutes),
                )
                await _require_duration_open(active_uow.session, next_employee_id, duration_to_submit, "FILING")
                await _verify_saved_days(active_uow.session, model, duration_to_submit)
            next_end_year = (next_end_at - timedelta(microseconds=1)).astimezone(ZoneInfo("Asia/Manila")).year
            if (
                next_employee_id != model.employee_id
                or next_leave_type_id != model.leave_type_id
                or next_year != model.start_at.astimezone(ZoneInfo("Asia/Manila")).year
                or next_end_year != (model.end_at - timedelta(microseconds=1)).astimezone(ZoneInfo("Asia/Manila")).year
            ):
                await _lock_matching_entitlements(
                    active_uow.session, next_employee_id, next_leave_type_id, next_year, next_end_year,
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

            if next_status == "PENDING" and model.status != "PENDING":
                await assign_org_approval(
                    active_uow.session,
                    resource_type="leave_application",
                    resource_id=model.id,
                    employee_id=next_employee_id,
                    assigned_by=actor_id,
                    on_date=datetime.now(ZoneInfo("Asia/Manila")).date(),
                    permission_code="leave.approve_team",
                    hold_unresolved=True,
                )
            for key, value in values.items():
                setattr(model, key, value)
            if duration is not None:
                await _replace_draft_days(active_uow.session, model.id, duration)
            if next_status == "APPROVED" and not was_approved:
                if actor_id is None:
                    raise ValueError("An actor is required to approve a leave application.")
                await _post_approved_leave_charge(active_uow.session, model, actor_id)
                model.approved_by_id = actor_id
            model.row_version += 1
            model.updated_at = datetime.now(timezone.utc)
            await active_uow.session.flush()
            await active_uow.session.refresh(model)
            return _to_entity(model, LeaveApplicationEntity)

    async def update(self, record_id: UUID, values: dict[str, Any]) -> LeaveApplicationEntity | None:
        before = await self.get(record_id)
        if before is None:
            return None
        return await self.update_with_approval_posting(
            record_id, values, values.get("updated_by", before.updated_by),
        )


class LeaveApplicationDateUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def create(self, values: dict[str, Any]) -> LeaveApplicationDateEntity:
        async with self.uow as uow:
            await self._require_open(uow.session, values["leave_application_id"], values["leave_date"])
            model = LeaveApplicationDateModel(**values)
            uow.session.add(model)
            await uow.session.flush()
            await uow.session.refresh(model)
            return _to_entity(model, LeaveApplicationDateEntity)

    async def _require_open(self, session: Any, application_id: UUID, leave_date: date) -> None:
        parent = await session.scalar(
            select(LeaveApplicationModel).where(LeaveApplicationModel.id == application_id)
            .with_for_update()
        )
        if parent is None:
            raise ValueError("Leave application not found.")
        stage: DeadlineStage = "FILING" if parent.status == "DRAFT" else "APPROVAL"
        await _require_leave_open(
            session, parent.employee_id, parent.start_at, parent.end_at, stage=stage,
        )
        await require_attendance_open(
            session, parent.employee_id, leave_date, leave_date, stage=stage,
        )

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
        async with self.uow as uow:
            model = await uow.session.scalar(
                select(LeaveApplicationDateModel).where(LeaveApplicationDateModel.id == record_id)
                .with_for_update()
            )
            if model is None:
                return None
            await self._require_open(uow.session, model.leave_application_id, model.leave_date)
            await self._require_open(
                uow.session, model.leave_application_id, values.get("leave_date", model.leave_date),
            )
            for key, value in values.items():
                setattr(model, key, value)
            await uow.session.flush()
            await uow.session.refresh(model)
            return _to_entity(model, LeaveApplicationDateEntity)

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
            await self._require_open(active_uow.session, model.leave_application_id, model.leave_date)
            await active_uow.session.delete(model)
            await active_uow.session.flush()
            return True


class LeaveLedgerUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def create(self, values: dict[str, Any]) -> LeaveLedgerEntity:
        async with self.uow as active_uow:
            session = active_uow.session
            await _lock_matching_entitlements(
                session, values["employee_id"], values["leave_type_id"],
                values["transaction_date"].year, values["transaction_date"].year,
            )
            model = LeaveLedgerModel(**values)
            session.add(model)
            await session.flush()
            await session.refresh(model)
            return _to_entity(model, LeaveLedgerEntity)

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
