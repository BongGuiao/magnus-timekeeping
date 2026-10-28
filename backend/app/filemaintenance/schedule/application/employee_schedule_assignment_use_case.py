from datetime import date, datetime, timezone
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.schedule.domain.entities.employee_schedule_assignment import (
    EmployeeScheduleAssignmentEntity,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    RestDayPatternModel,
    ScheduleTemplateModel,
)
from app.payroll.infrastructure.db_model import PayrollSystemParametersModel


class EmployeeScheduleAssignmentReferenceError(ValueError):
    pass


class EmployeeScheduleAssignmentValidationError(ValueError):
    pass


class EmployeeScheduleAssignmentConflictError(ValueError):
    pass


def _to_entity(
    model: EmployeeScheduleAssignmentModel,
) -> EmployeeScheduleAssignmentEntity:
    return EmployeeScheduleAssignmentEntity(
        id=model.id,
        employee_id=model.employee_id,
        schedule_template_id=model.schedule_template_id,
        rest_day_pattern_id=model.rest_day_pattern_id,
        assignment_type=model.assignment_type,
        attendance_mode=model.attendance_mode,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        reason=model.reason,
        approved_by=model.approved_by,
        approved_at=model.approved_at,
        status=model.status,
        created_at=model.created_at,
        created_by=model.created_by,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
        row_version=model.row_version,
        is_active=model.is_active,
    )


def _validate_period(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise EmployeeScheduleAssignmentValidationError(
            "effective_to must be on or after effective_from."
        )


async def _validate_references(
    uow: GenUnitOfWork,
    *,
    employee_id: UUID,
    schedule_template_id: UUID,
    rest_day_pattern_id: UUID | None,
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    if await uow.session.get(EmployeeModel, employee_id) is None:
        raise EmployeeScheduleAssignmentReferenceError("Employee not found.")
    if await uow.session.get(ScheduleTemplateModel, schedule_template_id) is None:
        raise EmployeeScheduleAssignmentReferenceError("Schedule template not found.")
    if rest_day_pattern_id is not None:
        if await uow.session.get(RestDayPatternModel, rest_day_pattern_id) is None:
            raise EmployeeScheduleAssignmentReferenceError("Rest day pattern not found.")


async def _schedule_approval_required(
    uow: GenUnitOfWork,
    schedule_template_id: UUID,
) -> bool:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    template = await uow.session.get(ScheduleTemplateModel, schedule_template_id)
    if template is None:
        raise EmployeeScheduleAssignmentReferenceError("Schedule template not found.")
    parameters = await uow.session.get(
        PayrollSystemParametersModel,
        template.company_id,
    )
    return parameters is None or parameters.schedule_assignment_approval_required


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in (
        "employee_schedule_assignments_employee_id_fkey",
        "employee_schedule_assignments_schedule_template_id_fkey",
        "employee_schedule_assignments_rest_day_pattern_id_fkey",
        "employee_schedule_assignments_approved_by_fkey",
    ):
        raise EmployeeScheduleAssignmentReferenceError(
            "An employee, schedule template, rest day pattern, or approver reference does not exist."
        ) from error
    raise error


class CreateEmployeeScheduleAssignmentUseCase(
    BaseUseCase[EmployeeScheduleAssignmentEntity],
):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        payload: dict[str, Any],
    ) -> EmployeeScheduleAssignmentEntity:
        _validate_period(payload["effective_from"], payload.get("effective_to"))
        try:
            async with self.uow as uow:
                await _validate_references(
                    uow,
                    employee_id=payload["employee_id"],
                    schedule_template_id=payload["schedule_template_id"],
                    rest_day_pattern_id=payload.get("rest_day_pattern_id"),
                )
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                approval_required = await _schedule_approval_required(
                    uow,
                    payload["schedule_template_id"],
                )
                now = datetime.now(timezone.utc)
                model = EmployeeScheduleAssignmentModel(
                    **payload,
                    attendance_mode=payload.get("attendance_mode", "PUNCH_REQUIRED"),
                    status="DRAFT" if approval_required else "APPROVED",
                    approved_by=None if approval_required else payload["created_by"],
                    approved_at=None if approval_required else now,
                )
                uow.session.add(model)
                await uow.session.flush()
                await uow.session.refresh(model)
                return _to_entity(model)
        except IntegrityError as error:
            _translate_integrity_error(error)


class ListEmployeeScheduleAssignmentsUseCase(
    BaseUseCase[list[EmployeeScheduleAssignmentEntity]],
):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        employee_id: UUID | None = None,
        schedule_template_id: UUID | None = None,
        rest_day_pattern_id: UUID | None = None,
        assignment_status: str | None = None,
        is_active: bool | None = None,
        effective_on: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EmployeeScheduleAssignmentEntity]:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            query = select(EmployeeScheduleAssignmentModel)
            if employee_id is not None:
                query = query.where(EmployeeScheduleAssignmentModel.employee_id == employee_id)
            if schedule_template_id is not None:
                query = query.where(
                    EmployeeScheduleAssignmentModel.schedule_template_id == schedule_template_id
                )
            if rest_day_pattern_id is not None:
                query = query.where(
                    EmployeeScheduleAssignmentModel.rest_day_pattern_id == rest_day_pattern_id
                )
            if assignment_status is not None:
                query = query.where(EmployeeScheduleAssignmentModel.status == assignment_status)
            if is_active is not None:
                query = query.where(EmployeeScheduleAssignmentModel.is_active.is_(is_active))
            if effective_on is not None:
                query = query.where(
                    EmployeeScheduleAssignmentModel.effective_from <= effective_on,
                    (
                        EmployeeScheduleAssignmentModel.effective_to.is_(None)
                        | (EmployeeScheduleAssignmentModel.effective_to >= effective_on)
                    ),
                )
            query = (
                query.order_by(
                    EmployeeScheduleAssignmentModel.employee_id,
                    EmployeeScheduleAssignmentModel.effective_from.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            models = (await uow.session.scalars(query)).all()
            return [_to_entity(model) for model in models]


class GetEmployeeScheduleAssignmentUseCase(
    BaseUseCase[EmployeeScheduleAssignmentEntity | None],
):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, assignment_id: UUID) -> EmployeeScheduleAssignmentEntity | None:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await uow.session.get(EmployeeScheduleAssignmentModel, assignment_id)
            return _to_entity(model) if model is not None else None


class UpdateEmployeeScheduleAssignmentUseCase(
    BaseUseCase[EmployeeScheduleAssignmentEntity | None],
):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        assignment_id: UUID,
        payload: dict[str, Any],
    ) -> EmployeeScheduleAssignmentEntity | None:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                model = await uow.session.get(EmployeeScheduleAssignmentModel, assignment_id)
                if model is None:
                    return None
                values = {
                    "employee_id": payload.get("employee_id", model.employee_id),
                    "schedule_template_id": payload.get(
                        "schedule_template_id",
                        model.schedule_template_id,
                    ),
                    "rest_day_pattern_id": payload.get(
                        "rest_day_pattern_id",
                        model.rest_day_pattern_id,
                    ),
                }
                await _validate_references(uow, **values)
                effective_from = payload.get("effective_from", model.effective_from)
                effective_to = payload.get("effective_to", model.effective_to)
                _validate_period(effective_from, effective_to)
                substantive_fields = {
                    "employee_id",
                    "schedule_template_id",
                    "rest_day_pattern_id",
                    "attendance_mode",
                    "assignment_type",
                    "effective_from",
                    "effective_to",
                    "reason",
                }
                if model.status == "APPROVED" and substantive_fields.intersection(payload):
                    if await _schedule_approval_required(
                        uow,
                        values["schedule_template_id"],
                    ):
                        model.status = "DRAFT"
                        model.approved_by = None
                        model.approved_at = None
                    else:
                        model.approved_by = payload.get("updated_by")
                        model.approved_at = datetime.now(timezone.utc)
                for key, value in payload.items():
                    setattr(model, key, value)
                model.row_version = (model.row_version or 0) + 1
                await uow.session.flush()
                await uow.session.refresh(model)
                return _to_entity(model)
        except IntegrityError as error:
            _translate_integrity_error(error)


class ApproveEmployeeScheduleAssignmentUseCase(
    BaseUseCase[EmployeeScheduleAssignmentEntity | None],
):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        assignment_id: UUID,
        approver_id: UUID,
    ) -> EmployeeScheduleAssignmentEntity | None:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                model = await uow.session.get(EmployeeScheduleAssignmentModel, assignment_id)
                if model is None:
                    return None
                if model.status == "APPROVED":
                    raise EmployeeScheduleAssignmentConflictError(
                        "This employee schedule assignment is already approved."
                    )
                if not model.is_active:
                    raise EmployeeScheduleAssignmentConflictError(
                        "An inactive employee schedule assignment cannot be approved."
                    )
                model.status = "APPROVED"
                model.approved_by = approver_id
                model.approved_at = datetime.now(timezone.utc)
                model.updated_by = approver_id
                model.row_version = (model.row_version or 0) + 1
                await uow.session.flush()
                await uow.session.refresh(model)
                return _to_entity(model)
        except IntegrityError as error:
            _translate_integrity_error(error)


class DeactivateEmployeeScheduleAssignmentUseCase(
    BaseUseCase[EmployeeScheduleAssignmentEntity | None],
):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, assignment_id: UUID, actor_id: UUID) -> EmployeeScheduleAssignmentEntity | None:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await uow.session.get(EmployeeScheduleAssignmentModel, assignment_id)
            if model is None:
                return None
            model.is_active = False
            model.updated_by = actor_id
            model.row_version = (model.row_version or 0) + 1
            await uow.session.flush()
            await uow.session.refresh(model)
            return _to_entity(model)
