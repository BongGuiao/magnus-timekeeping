from dataclasses import fields
from datetime import date
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.domain.entities.overtime import (
    OvertimeApplication,
    OvertimeApplicationRecord,
    OvertimeAttendance,
    OvertimeCutoff,
)
from app.attendance.domain.overtime_rules import OPEN_APPLICATION_STATUSES
from app.attendance.infrastructure.db_model import AttendanceModel, OvertimeApplicationModel
from app.attendance.infrastructure.entity_mapping import copy_fields as _copy_fields
from app.attendance.infrastructure.entity_mapping import to_attendance_employee as _employee
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleSegmentModel

_ATTENDANCE_OVERTIME_FIELDS = (
    "calculated_ot_minutes",
    "overtime_hours",
    "regular_overtime_minutes",
    "regular_overtime_hours",
    "night_differential_overtime_minutes",
    "night_differential_overtime_hours",
    "expected_clock_in_at",
    "expected_clock_out_at",
    "late_minutes",
    "undertime_minutes",
    "night_differential_minutes",
    "night_differential_hours",
    "punch_metadata",
    "overtime_request_status",
    "requested_regular_overtime_minutes",
    "requested_night_differential_overtime_minutes",
    "requested_night_differential_minutes",
    "overtime_requested_at",
    "approved_regular_overtime_minutes",
    "approved_night_differential_overtime_minutes",
    "approved_night_differential_minutes",
    "overtime_approved_by_id",
    "overtime_approved_at",
    "approved_ot_worked",
    "approved_night_diff",
)
_APPLICATION_DECISION_FIELDS = (
    "status",
    "supervisor_approved_minutes",
    "final_payable_minutes",
    "updated_by",
    "row_version",
)


def current_overtime_cutoff_statement(employee_id: UUID, today: date):
    return (
        select(PayrollCutoffModel)
        .join(
            EmploymentAssignmentModel,
            EmploymentAssignmentModel.payroll_group_id == PayrollCutoffModel.payroll_group_id,
        )
        .where(
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= today),
            or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= today),
            PayrollCutoffModel.is_active.is_(True),
            PayrollCutoffModel.period_start <= today,
            PayrollCutoffModel.period_end >= today,
        )
        .order_by(PayrollCutoffModel.period_start.desc(), PayrollCutoffModel.period_end.desc(), PayrollCutoffModel.id)
        .limit(1)
    )


def latest_configured_overtime_cutoff_statement(employee_id: UUID, today: date):
    return (
        select(PayrollCutoffModel)
        .join(
            EmploymentAssignmentModel,
            EmploymentAssignmentModel.payroll_group_id == PayrollCutoffModel.payroll_group_id,
        )
        .where(
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= today),
            or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= today),
            PayrollCutoffModel.is_active.is_(True),
        )
        .order_by(
            PayrollCutoffModel.period_end.desc(),
            PayrollCutoffModel.period_start.desc(),
            PayrollCutoffModel.id,
        )
        .limit(1)
    )


def _record(row) -> OvertimeApplicationRecord:
    application, attendance, employee = row
    return OvertimeApplicationRecord(
        _copy_fields(application, OvertimeApplication),
        _copy_fields(attendance, OvertimeAttendance),
        _employee(employee),
    )


def _supervised_by(statement, supervisor_employee_id: UUID):
    return statement.join(
        EmploymentAssignmentModel,
        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
    ).where(
        EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= AttendanceModel.work_date,
        or_(
            EmploymentAssignmentModel.effective_to.is_(None),
            EmploymentAssignmentModel.effective_to >= AttendanceModel.work_date,
        ),
        or_(
            EmploymentAssignmentModel.separation_date.is_(None),
            EmploymentAssignmentModel.separation_date >= AttendanceModel.work_date,
        ),
    )


class SqlAlchemyOvertimeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_active_employee_id_for_user(self, user_id: UUID) -> Optional[UUID]:
        return await self._session.scalar(
            select(EmployeeModel.id)
            .join(UserModel, UserModel.employee_id == EmployeeModel.id)
            .where(UserModel.id == user_id, EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE")
        )

    async def get_user_id_for_employee(self, employee_id: UUID) -> Optional[UUID]:
        return await self._session.scalar(
            select(UserModel.id).where(UserModel.employee_id == employee_id).limit(1)
        )

    async def get_current_cutoff(self, employee_id: UUID, today: date) -> Optional[OvertimeCutoff]:
        cutoff = await self._session.scalar(current_overtime_cutoff_statement(employee_id, today))
        return _copy_fields(cutoff, OvertimeCutoff) if cutoff is not None else None

    async def get_latest_configured_cutoff(
        self, employee_id: UUID, today: date
    ) -> Optional[OvertimeCutoff]:
        cutoff = await self._session.scalar(
            latest_configured_overtime_cutoff_statement(employee_id, today)
        )
        return _copy_fields(cutoff, OvertimeCutoff) if cutoff is not None else None

    async def get_cutoff_for_employee_on_date(
        self,
        employee_id: UUID,
        work_date: date,
    ) -> Optional[OvertimeCutoff]:
        cutoff = await self._session.scalar(
            current_overtime_cutoff_statement(employee_id, work_date)
        )
        return _copy_fields(cutoff, OvertimeCutoff) if cutoff is not None else None

    async def list_completed_attendance_in_period(
        self, user_id: UUID, period_start: date, period_end: date
    ) -> list[OvertimeAttendance]:
        rows = (
            await self._session.execute(
                select(AttendanceModel)
                .where(
                    AttendanceModel.user_id == user_id,
                    AttendanceModel.record_status == "VALID",
                    AttendanceModel.work_date >= period_start,
                    AttendanceModel.work_date <= period_end,
                    func.coalesce(AttendanceModel.corrected_clock_in_at, AttendanceModel.clock_in_at).is_not(None),
                    func.coalesce(AttendanceModel.corrected_clock_out_at, AttendanceModel.clock_out_at)
                    > func.coalesce(AttendanceModel.corrected_clock_in_at, AttendanceModel.clock_in_at),
                )
                .order_by(AttendanceModel.work_date.desc(), AttendanceModel.created_at.desc())
            )
        ).scalars().all()
        return [_copy_fields(row, OvertimeAttendance) for row in rows]

    async def list_employee_attendance_in_range(
        self,
        employee_id: UUID,
        from_date: date,
        to_date: date,
        *,
        lock_for_update: bool = False,
    ) -> list[OvertimeAttendance]:
        statement = (
            select(AttendanceModel)
            .join(UserModel, UserModel.id == AttendanceModel.user_id)
            .where(
                UserModel.employee_id == employee_id,
                AttendanceModel.work_date >= from_date,
                AttendanceModel.work_date <= to_date,
                AttendanceModel.record_status == "VALID",
            )
            .order_by(AttendanceModel.work_date, AttendanceModel.created_at, AttendanceModel.id)
        )
        if lock_for_update:
            statement = statement.with_for_update(of=AttendanceModel)
        rows = (
            await self._session.execute(
                statement
            )
        ).scalars().all()
        return [_copy_fields(row, OvertimeAttendance) for row in rows]

    async def list_break_rules_for_template(
        self, schedule_template_id: UUID
    ) -> list[dict[str, Any]]:
        segments = (
            await self._session.scalars(
                select(ScheduleSegmentModel)
                .where(
                    ScheduleSegmentModel.schedule_template_id == schedule_template_id,
                    ScheduleSegmentModel.break_slot.is_not(None),
                )
                .order_by(ScheduleSegmentModel.segment_sequence)
            )
        ).all()
        return [
            {
                "break_slot": segment.break_slot,
                "segment_type": segment.segment_type,
                "break_minutes": segment.break_minutes,
                "auto_deduct": segment.auto_deduct,
            }
            for segment in segments
        ]

    async def lock_completed_attendance(
        self, attendance_id: UUID, user_id: UUID
    ) -> Optional[tuple[OvertimeAttendance, AttendanceEmployee]]:
        row = (
            await self._session.execute(
                select(AttendanceModel, EmployeeModel)
                .with_for_update(of=AttendanceModel)
                .join(UserModel, UserModel.id == AttendanceModel.user_id)
                .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
                .where(
                    AttendanceModel.id == attendance_id,
                    AttendanceModel.user_id == user_id,
                    AttendanceModel.record_status == "VALID",
                    or_(
                        AttendanceModel.corrected_clock_out_at.is_not(None),
                        AttendanceModel.clock_out_at.is_not(None),
                    ),
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                )
            )
        ).first()
        if row is None:
            return None
        attendance, employee = row
        return _copy_fields(attendance, OvertimeAttendance), _employee(employee)

    async def has_open_application(
        self,
        attendance_id: UUID,
        overtime_type: Optional[str] = None,
        exclude_application_id: Optional[UUID] = None,
    ) -> bool:
        statement = select(OvertimeApplicationModel.id).where(
            OvertimeApplicationModel.attendance_record_id == attendance_id,
            OvertimeApplicationModel.is_active.is_(True),
            OvertimeApplicationModel.status.in_(OPEN_APPLICATION_STATUSES),
        )
        if overtime_type is not None:
            statement = statement.where(OvertimeApplicationModel.overtime_type == overtime_type)
        if exclude_application_id is not None:
            statement = statement.where(OvertimeApplicationModel.id != exclude_application_id)
        return await self._session.scalar(statement.limit(1)) is not None

    async def add_application(self, application: OvertimeApplication) -> OvertimeApplication:
        values = {field.name: getattr(application, field.name) for field in fields(OvertimeApplication)}
        if values["id"] is None:
            del values["id"]
        model = OvertimeApplicationModel(**values)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _copy_fields(model, OvertimeApplication)

    async def save_application(self, application: OvertimeApplication) -> None:
        model = await self._session.get(OvertimeApplicationModel, application.id)
        for name in (
            "requested_start_at",
            "requested_end_at",
            "potential_ot_minutes",
            "requested_minutes",
            "system_validated_minutes",
            "supervisor_approved_minutes",
            "final_payable_minutes",
            "overtime_type",
            "reason",
            "work_accomplished",
            "validation_status",
            *_APPLICATION_DECISION_FIELDS,
        ):
            setattr(model, name, getattr(application, name))
        await self._session.flush()

    async def save_attendance(self, attendance: OvertimeAttendance) -> None:
        model = await self._session.get(AttendanceModel, attendance.id)
        for name in _ATTENDANCE_OVERTIME_FIELDS:
            setattr(model, name, getattr(attendance, name))
        await self._session.flush()

    async def list_applications_for_attendance(self, attendance_id: UUID) -> Sequence[OvertimeApplication]:
        rows = (
            await self._session.scalars(
                select(OvertimeApplicationModel)
                .where(
                    OvertimeApplicationModel.attendance_record_id == attendance_id,
                    OvertimeApplicationModel.is_active.is_(True),
                )
                .order_by(OvertimeApplicationModel.updated_at.desc(), OvertimeApplicationModel.id.desc())
            )
        ).all()
        return [_copy_fields(row, OvertimeApplication) for row in rows]

    async def list_applications_for_user(self, user_id: UUID) -> list[OvertimeApplicationRecord]:
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .join(AttendanceModel, AttendanceModel.id == OvertimeApplicationModel.attendance_record_id)
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .join(UserModel, UserModel.employee_id == EmployeeModel.id)
            .where(UserModel.id == user_id, OvertimeApplicationModel.is_active.is_(True))
            .order_by(
                OvertimeApplicationModel.attendance_date.desc(),
                OvertimeApplicationModel.created_at.desc(),
            )
        )
        return [_record(row) for row in (await self._session.execute(statement)).all()]

    async def list_pending_applications(
        self, supervisor_employee_id: Optional[UUID]
    ) -> list[OvertimeApplicationRecord]:
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .join(AttendanceModel, AttendanceModel.id == OvertimeApplicationModel.attendance_record_id)
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .where(
                OvertimeApplicationModel.status == "PENDING",
                OvertimeApplicationModel.is_active.is_(True),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
            )
            .order_by(OvertimeApplicationModel.created_at, EmployeeModel.employee_no)
        )
        if supervisor_employee_id is not None:
            statement = _supervised_by(statement, supervisor_employee_id).distinct()
        return [_record(row) for row in (await self._session.execute(statement)).all()]

    async def lock_pending_application(
        self, application_id: UUID, supervisor_employee_id: Optional[UUID]
    ) -> Optional[OvertimeApplicationRecord]:
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .with_for_update(of=(OvertimeApplicationModel, AttendanceModel))
            .join(AttendanceModel, AttendanceModel.id == OvertimeApplicationModel.attendance_record_id)
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .where(
                OvertimeApplicationModel.id == application_id,
                OvertimeApplicationModel.status == "PENDING",
                OvertimeApplicationModel.is_active.is_(True),
            )
        )
        if supervisor_employee_id is not None:
            statement = _supervised_by(statement, supervisor_employee_id)
        row = (await self._session.execute(statement)).first()
        return _record(row) if row is not None else None

    async def lock_owned_application(
        self, application_id: UUID, user_id: UUID
    ) -> Optional[OvertimeApplicationRecord]:
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .with_for_update(of=(OvertimeApplicationModel, AttendanceModel))
            .join(AttendanceModel, AttendanceModel.id == OvertimeApplicationModel.attendance_record_id)
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .join(UserModel, UserModel.employee_id == EmployeeModel.id)
            .where(
                OvertimeApplicationModel.id == application_id,
                OvertimeApplicationModel.is_active.is_(True),
                UserModel.id == user_id,
            )
        )
        row = (await self._session.execute(statement)).first()
        return _record(row) if row is not None else None
