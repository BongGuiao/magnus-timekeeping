import logging
from datetime import date
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.attendance.domain.entities.admin_dashboard import (
    PendingLeaveSummary,
    PunchedEmployeeToday,
    TeamAttendanceDay,
    WeeklyAttendanceSample,
)
from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.auth.infrastructure.approval_routing import (
    ApprovalRoutingError,
    active_assignment_conditions,
    approval_route_scope,
    legacy_supervisor_scope,
    resolve_org_unit_approver_from_hierarchy,
)
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit

logger = logging.getLogger(__name__)


def _employee_columns(model, prefix: str):
    return [
        model.id.label(f"{prefix}id"),
        model.employee_no.label(f"{prefix}employee_no"),
        model.first_name.label(f"{prefix}first_name"),
        model.middle_name.label(f"{prefix}middle_name"),
        model.last_name.label(f"{prefix}last_name"),
        model.suffix.label(f"{prefix}suffix"),
        model.preferred_name.label(f"{prefix}preferred_name"),
    ]


def _employee_group_columns(model):
    return [
        model.id,
        model.employee_no,
        model.first_name,
        model.middle_name,
        model.last_name,
        model.suffix,
        model.preferred_name,
    ]


def _employee_from(row, prefix: str) -> AttendanceEmployee:
    values = row._mapping
    return AttendanceEmployee(
        id=values[f"{prefix}id"],
        employee_no=values[f"{prefix}employee_no"],
        first_name=values[f"{prefix}first_name"],
        middle_name=values[f"{prefix}middle_name"],
        last_name=values[f"{prefix}last_name"],
        suffix=values[f"{prefix}suffix"],
        preferred_name=values[f"{prefix}preferred_name"],
    )


def _clock_in_location(punch_metadata) -> str | None:
    if not isinstance(punch_metadata, dict):
        return None
    clock_in = punch_metadata.get("clock_in")
    if not isinstance(clock_in, dict):
        return None
    geofence = clock_in.get("geofence_validation")
    if not isinstance(geofence, dict):
        return None
    location_name = geofence.get("location_name")
    if isinstance(location_name, str) and location_name.strip():
        return location_name.strip()
    if geofence.get("work_location_type") == "WFH":
        return "Registered WFH location"
    return None


class SqlAlchemyAdminDashboardRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_employees_punched_on_day(
        self, work_date: date, approver_employee_id: UUID | None = None
    ) -> list[PunchedEmployeeToday]:
        ClockInAttendance = aliased(AttendanceModel)
        ClockInUser = aliased(UserModel)
        clock_in_metadata = (
            select(ClockInAttendance.punch_metadata)
            .select_from(ClockInAttendance)
            .join(ClockInUser, ClockInUser.id == ClockInAttendance.user_id)
            .where(
                ClockInUser.employee_id == EmployeeModel.id,
                ClockInUser.is_active.is_(True),
                ClockInUser.account_status == "ACTIVE",
                ClockInAttendance.work_date == work_date,
                ClockInAttendance.record_status == "VALID",
                ClockInAttendance.clock_in_at.is_not(None),
                not_merged_source(ClockInAttendance),
            )
            .order_by(ClockInAttendance.clock_in_at.asc(), ClockInAttendance.id.asc())
            .limit(1)
            .correlate(EmployeeModel)
            .scalar_subquery()
        )
        conditions = [
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            AttendanceModel.record_status == "VALID",
            not_merged_source(),
            AttendanceModel.work_date == work_date,
            or_(
                AttendanceModel.clock_in_at.is_not(None),
                AttendanceModel.clock_out_at.is_not(None),
            ),
        ]
        if approver_employee_id is None:
            rows = (
                await self._session.execute(
                    select(
                        *_employee_columns(EmployeeModel, "employee_"),
                        func.min(AttendanceModel.clock_in_at).label("clock_in_at"),
                        func.max(AttendanceModel.clock_out_at).label("clock_out_at"),
                        clock_in_metadata.label("clock_in_metadata"),
                    )
                    .select_from(EmployeeModel)
                    .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                    .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                    .where(*conditions)
                    .group_by(*_employee_group_columns(EmployeeModel))
                    .order_by(EmployeeModel.employee_no)
                )
            ).all()
            return [
                PunchedEmployeeToday(
                    employee=_employee_from(row, "employee_"),
                    clock_in_at=row._mapping["clock_in_at"],
                    clock_out_at=row._mapping["clock_out_at"],
                    clock_in_location=_clock_in_location(row._mapping["clock_in_metadata"]),
                )
                for row in rows
            ]

        punch_rows = (
            await self._session.execute(
                select(
                    *_employee_columns(EmployeeModel, "employee_"),
                    EmploymentAssignmentModel.company_id.label("company_id"),
                    EmploymentAssignmentModel.org_unit_id.label("org_unit_id"),
                    func.min(AttendanceModel.clock_in_at).label("clock_in_at"),
                    func.max(AttendanceModel.clock_out_at).label("clock_out_at"),
                    clock_in_metadata.label("clock_in_metadata"),
                )
                .select_from(EmployeeModel)
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .join(EmploymentAssignmentModel, EmploymentAssignmentModel.employee_id == EmployeeModel.id)
                .where(*conditions, *active_assignment_conditions(work_date))
                .group_by(
                    *_employee_group_columns(EmployeeModel),
                    EmploymentAssignmentModel.company_id,
                    EmploymentAssignmentModel.org_unit_id,
                )
                .order_by(EmployeeModel.employee_no)
            )
        ).all()
        assignments_by_employee: dict[UUID, set[tuple[UUID, UUID | None]]] = {}
        punches_by_employee: dict[UUID, PunchedEmployeeToday] = {}
        company_ids: set[UUID] = set()
        for row in punch_rows:
            values = row._mapping
            employee = _employee_from(row, "employee_")
            employee_id = employee.id
            company_id = values["company_id"]
            source_unit_id = values["org_unit_id"]
            assignments_by_employee.setdefault(employee_id, set()).add((company_id, source_unit_id))
            company_ids.add(company_id)
            punches_by_employee[employee_id] = PunchedEmployeeToday(
                employee=employee,
                clock_in_at=values["clock_in_at"],
                clock_out_at=values["clock_out_at"],
                clock_in_location=_clock_in_location(values["clock_in_metadata"]),
            )

        org_units = (
            await self._session.scalars(
                select(OrgUnit).where(OrgUnit.company_id.in_(company_ids))
            )
        ).all() if company_ids else []
        org_units_by_id = {unit.id: unit for unit in org_units}

        punched_employees: list[PunchedEmployeeToday] = []
        unresolved_count = 0
        for employee_id, assignments in assignments_by_employee.items():
            if len(assignments) != 1:
                unresolved_count += 1
                continue
            company_id, source_unit_id = next(iter(assignments))
            try:
                approver = resolve_org_unit_approver_from_hierarchy(
                    employee_id,
                    company_id,
                    source_unit_id,
                    work_date,
                    org_units_by_id,
                )
            except ApprovalRoutingError:
                unresolved_count += 1
                continue
            if approver.employee_id == approver_employee_id:
                punched_employees.append(punches_by_employee[employee_id])

        if unresolved_count:
            logger.warning(
                "Skipped %s punched employee(s) with unresolved Org Chart approval assignments.",
                unresolved_count,
            )
        return sorted(punched_employees, key=lambda punched: punched.employee.employee_no)

    async def list_team_attendance(
        self, supervisor_employee_id: UUID, today: date, month_start: date
    ) -> list[TeamAttendanceDay]:
        SupervisorModel = aliased(EmployeeModel)
        rows = (
            await self._session.execute(
                select(
                    *_employee_columns(EmployeeModel, "employee_"),
                    *_employee_columns(SupervisorModel, "supervisor_"),
                    AttendanceModel.work_date,
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                    AttendanceModel.corrected_clock_out_at,
                    AttendanceModel.clock_out_at,
                    AttendanceModel.expected_clock_in_at,
                    AttendanceModel.expected_clock_out_at,
                    AttendanceModel.is_absent,
                    AttendanceModel.leave_type,
                )
                .distinct()
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .join(
                    SupervisorModel,
                    SupervisorModel.id == EmploymentAssignmentModel.supervisor_employee_id,
                )
                .where(
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                    UserModel.is_active.is_(True),
                    UserModel.account_status == "ACTIVE",
                    SupervisorModel.is_active.is_(True),
                    SupervisorModel.record_status == "ACTIVE",
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                    AttendanceModel.record_status == "VALID",
                    not_merged_source(),
                    AttendanceModel.work_date >= month_start,
                    AttendanceModel.work_date <= today,
                )
                .order_by(AttendanceModel.work_date.desc(), EmployeeModel.employee_no)
            )
        ).all()
        return [
            TeamAttendanceDay(
                employee=_employee_from(row, "employee_"),
                supervisor=_employee_from(row, "supervisor_"),
                work_date=row.work_date,
                clock_in_at=row.corrected_clock_in_at or row.clock_in_at,
                clock_out_at=row.corrected_clock_out_at or row.clock_out_at,
                expected_clock_out_at=row.expected_clock_out_at,
                expected_clock_in_at=row.expected_clock_in_at,
                is_absent=row.is_absent,
                leave_type=row.leave_type,
            )
            for row in rows
        ]

    async def list_pending_leaves(
        self, supervisor_employee_id: UUID | None = None, today: date | None = None
    ) -> list[PendingLeaveSummary]:
        conditions = [
            LeaveApplicationModel.is_active.is_(True),
            LeaveApplicationModel.status == "PENDING",
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
        ]
        if supervisor_employee_id is not None:
            if today is None:
                raise ValueError("A date is required when loading team-scoped leave applications.")
            conditions.append(approval_route_scope(
                "leave_application",
                LeaveApplicationModel.id,
                supervisor_employee_id,
                legacy_supervisor_scope(EmployeeModel.id, supervisor_employee_id, today),
            ))
            conditions.append(EmployeeModel.id != supervisor_employee_id)
        rows = (
            await self._session.execute(
                select(
                    LeaveApplicationModel.id,
                    LeaveApplicationModel.application_no,
                    *_employee_columns(EmployeeModel, "employee_"),
                    LeaveTypeModel.leave_name.label("leave_type"),
                    LeaveApplicationModel.start_at,
                    LeaveApplicationModel.end_at,
                    LeaveApplicationModel.requested_minutes,
                    LeaveApplicationModel.status,
                )
                .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
                .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
                .where(*conditions)
                .order_by(LeaveApplicationModel.start_at, EmployeeModel.employee_no)
            )
        ).all()
        return [
            PendingLeaveSummary(
                id=row.id,
                application_no=row.application_no,
                employee=_employee_from(row, "employee_"),
                leave_type=row.leave_type,
                start_at=row.start_at,
                end_at=row.end_at,
                requested_minutes=row.requested_minutes,
                status=row.status,
            )
            for row in rows
        ]

    async def list_weekly_attendance(
        self,
        week_start: date,
        today: date,
        supervisor_employee_id: UUID | None = None,
    ) -> list[WeeklyAttendanceSample]:
        conditions = [
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            AttendanceModel.record_status == "VALID",
            not_merged_source(),
            AttendanceModel.work_date >= week_start,
            AttendanceModel.work_date <= today,
        ]
        if supervisor_employee_id is not None:
            conditions.append(
                exists(
                    select(EmploymentAssignmentModel.id).where(
                        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                        EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                        EmploymentAssignmentModel.is_active.is_(True),
                        EmploymentAssignmentModel.status == "ACTIVE",
                        EmploymentAssignmentModel.effective_from <= today,
                        or_(
                            EmploymentAssignmentModel.effective_to.is_(None),
                            EmploymentAssignmentModel.effective_to >= today,
                        ),
                        or_(
                            EmploymentAssignmentModel.separation_date.is_(None),
                            EmploymentAssignmentModel.separation_date >= today,
                        ),
                    )
                )
            )
        rows = (
            await self._session.execute(
                select(
                    *_employee_columns(EmployeeModel, "employee_"),
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                    AttendanceModel.corrected_clock_out_at,
                    AttendanceModel.clock_out_at,
                    AttendanceModel.punch_metadata,
                )
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .where(*conditions)
            )
        ).all()
        return [
            WeeklyAttendanceSample(
                employee=_employee_from(row, "employee_"),
                clock_in_at=row.corrected_clock_in_at or row.clock_in_at,
                clock_out_at=row.corrected_clock_out_at or row.clock_out_at,
                punch_metadata=row.punch_metadata,
            )
            for row in rows
        ]
