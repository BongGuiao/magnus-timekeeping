from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional
from uuid import UUID, uuid4

from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.overtime_ports import OvertimeUnitOfWork
from app.attendance.application.ports import AuditTrail, RecentAttendanceRefresher
from app.attendance.domain import overtime_rules as rules
from app.attendance.domain.entities.overtime import (
    OvertimeApplication,
    OvertimeApplicationRecord,
    OvertimeAttendance,
    OvertimeCutoff,
)
from app.attendance.domain.exceptions import ConflictError, RecordNotFoundError
from app.core.generics.uc_base import BaseUseCase


@dataclass
class OvertimeAttendanceOptions:
    cutoff: OvertimeCutoff
    attendance: list[OvertimeAttendance]


class _OvertimeUseCase:
    def __init__(self, uow: OvertimeUnitOfWork, clock: Callable[[], datetime] = utc_now):
        self._uow = uow
        self._clock = clock

    def _today(self):
        return ph_today(self._clock())


@dataclass
class GetOvertimeAttendanceOptionsInput:
    user_id: UUID


class GetOvertimeAttendanceOptionsUseCase(_OvertimeUseCase, BaseUseCase[OvertimeAttendanceOptions]):
    async def _execute(self, data: GetOvertimeAttendanceOptionsInput) -> OvertimeAttendanceOptions:
        async with self._uow as uow:
            employee_id = await uow.overtime.get_active_employee_id_for_user(data.user_id)
            if employee_id is None:
                raise RecordNotFoundError("An active employee linked to your account was not found.")
            cutoff = rules.validate_cutoff(
                await uow.overtime.get_current_cutoff(employee_id, self._today())
            )
            attendance = await uow.overtime.list_completed_attendance_in_period(
                data.user_id, cutoff.period_start, cutoff.period_end
            )
            return OvertimeAttendanceOptions(cutoff=cutoff, attendance=attendance)


@dataclass
class SubmitOvertimeApplicationInput:
    user_id: UUID
    attendance_id: UUID
    overtime_type: str
    requested_minutes: int
    reason: str
    work_accomplished: Optional[str] = None
    requested_start_at: Optional[datetime] = None
    requested_end_at: Optional[datetime] = None


class SubmitOvertimeApplicationUseCase(_OvertimeUseCase, BaseUseCase[OvertimeApplicationRecord]):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: SubmitOvertimeApplicationInput) -> OvertimeApplicationRecord:
        async with self._uow as uow:
            locked = await uow.overtime.lock_completed_attendance(data.attendance_id, data.user_id)
            if locked is None:
                raise RecordNotFoundError("Completed attendance record was not found for your account.")
            attendance, employee = locked

            rules.validate_cutoff(
                await uow.overtime.get_current_cutoff(employee.id, self._today()),
                attendance.work_date,
            )

            has_open_application = await uow.overtime.has_open_application(attendance.id)
            if (
                attendance.overtime_request_status in rules.OPEN_APPLICATION_STATUSES
                and not has_open_application
            ):
                raise ConflictError("An overtime request already exists for this attendance record.")
            if await uow.overtime.has_open_application(attendance.id, data.overtime_type):
                raise ConflictError("This overtime type already has a pending or approved application.")

            available_minutes = rules.calculated_minutes(attendance, data.overtime_type)
            rules.validate_requested_minutes(available_minutes, data.requested_minutes)

            requested_start_at, requested_end_at = rules.resolve_requested_period(
                attendance, data.overtime_type, data.requested_start_at, data.requested_end_at
            )
            rules.validate_application_period(
                requested_start_at=requested_start_at,
                requested_end_at=requested_end_at,
                actual_start_at=attendance.effective_clock_in,
                actual_end_at=attendance.effective_clock_out,
                requested_minutes=data.requested_minutes,
            )

            application = await uow.overtime.add_application(
                OvertimeApplication(
                    application_no=f"OT-{attendance.work_date:%Y%m%d}-{uuid4().hex[:12].upper()}",
                    employee_id=employee.id,
                    attendance_record_id=attendance.id,
                    attendance_date=attendance.work_date,
                    requested_start_at=requested_start_at,
                    requested_end_at=requested_end_at,
                    potential_ot_minutes=available_minutes,
                    requested_minutes=data.requested_minutes,
                    system_validated_minutes=data.requested_minutes,
                    overtime_type=data.overtime_type,
                    reason=data.reason,
                    work_accomplished=data.work_accomplished,
                    validation_status="VALID",
                    status="PENDING",
                    created_by=data.user_id,
                    updated_by=data.user_id,
                )
            )
            attendance.overtime_requested_at = self._clock()
            rules.apply_application_totals(
                attendance, await uow.overtime.list_applications_for_attendance(attendance.id)
            )
            await uow.overtime.save_attendance(attendance)
            result = OvertimeApplicationRecord(application, attendance, employee)

        self._refresher.request_refresh(data.user_id)
        await self._audit.record(
            user_id=data.user_id,
            action="SUBMIT",
            resource="overtime_application",
            resource_id=str(application.id),
            after={
                "application_no": application.application_no,
                "attendance_record_id": str(data.attendance_id),
                "overtime_type": data.overtime_type,
                "requested_minutes": data.requested_minutes,
                "requested_start_at": application.requested_start_at.isoformat(),
                "requested_end_at": application.requested_end_at.isoformat(),
            },
        )
        return result


@dataclass
class ListMyOvertimeApplicationsInput:
    user_id: UUID


class ListMyOvertimeApplicationsUseCase(_OvertimeUseCase, BaseUseCase[list[OvertimeApplicationRecord]]):
    async def _execute(self, data: ListMyOvertimeApplicationsInput) -> list[OvertimeApplicationRecord]:
        async with self._uow as uow:
            return await uow.overtime.list_applications_for_user(data.user_id)


@dataclass
class ListPendingOvertimeApplicationsInput:
    """supervisor_employee_id is None for administrators, who see every pending application."""

    supervisor_employee_id: Optional[UUID]


class ListPendingOvertimeApplicationsUseCase(
    _OvertimeUseCase, BaseUseCase[list[OvertimeApplicationRecord]]
):
    async def _execute(
        self, data: ListPendingOvertimeApplicationsInput
    ) -> list[OvertimeApplicationRecord]:
        async with self._uow as uow:
            return await uow.overtime.list_pending_applications(data.supervisor_employee_id)


@dataclass
class DecideOvertimeApplicationInput:
    application_id: UUID
    actor_id: UUID
    actor_employee_id: Optional[UUID]
    is_admin: bool
    decision: str
    supervisor_approved_minutes: int


class DecideOvertimeApplicationUseCase(_OvertimeUseCase, BaseUseCase[OvertimeApplicationRecord]):
    def __init__(
        self,
        uow: OvertimeUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        super().__init__(uow, clock)
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: DecideOvertimeApplicationInput) -> OvertimeApplicationRecord:
        supervisor_scope = None if data.is_admin else data.actor_employee_id
        async with self._uow as uow:
            record = await uow.overtime.lock_pending_application(data.application_id, supervisor_scope)
            if record is None:
                raise RecordNotFoundError(
                    "Pending overtime application was not found for your assigned employees."
                )
            application, attendance, employee = record.application, record.attendance, record.employee
            approved_minutes = data.supervisor_approved_minutes
            rules.validate_decision(
                application, employee.id, data.actor_employee_id, data.decision, approved_minutes
            )

            application.status = data.decision
            application.supervisor_approved_minutes = approved_minutes
            application.final_payable_minutes = approved_minutes if data.decision == "APPROVED" else 0
            application.updated_by = data.actor_id
            application.row_version += 1
            await uow.overtime.save_application(application)

            rules.apply_application_totals(
                attendance, await uow.overtime.list_applications_for_attendance(attendance.id)
            )
            attendance.overtime_approved_by_id = data.actor_id
            attendance.overtime_approved_at = self._clock()
            await uow.overtime.save_attendance(attendance)
            employee_user_id = await uow.overtime.get_user_id_for_employee(employee.id)

        if employee_user_id is not None:
            self._refresher.request_refresh(employee_user_id)
        await self._audit.record(
            user_id=data.actor_id,
            action=data.decision,
            resource="overtime_application",
            resource_id=str(data.application_id),
            after={
                "supervisor_approved_minutes": approved_minutes,
                "final_payable_minutes": application.final_payable_minutes,
            },
        )
        return record
