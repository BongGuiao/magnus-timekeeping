from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.domain.entities.attendance_review import (
    ReviewableAttendance,
    ReviewableAttendanceRecord,
    UnresolvedAttendanceRouting,
)
from app.attendance.domain.exceptions import RecordNotFoundError
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.entity_mapping import copy_fields, to_attendance_employee
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.approval_routing import (
    ApprovalRoutingError,
    approval_route_scope,
    assign_org_approval,
    legacy_supervisor_scope,
)
from app.auth.infrastructure.approval_routing_model import ApprovalRouteModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import require_attendance_open


def _review_scope(supervisor_employee_id: Optional[UUID], actor_employee_id: Optional[UUID], today: date):
    legacy = (
        legacy_supervisor_scope(EmployeeModel.id, supervisor_employee_id, today)
        if supervisor_employee_id is not None else true()
    )
    reviewer_id = supervisor_employee_id or actor_employee_id
    return and_(
        approval_route_scope("invalid_attendance", AttendanceModel.id, reviewer_id, legacy),
        EmployeeModel.id != reviewer_id if reviewer_id is not None else true(),
    )


def _record(attendance: AttendanceModel, employee: EmployeeModel) -> ReviewableAttendanceRecord:
    return ReviewableAttendanceRecord(
        copy_fields(attendance, ReviewableAttendance), to_attendance_employee(employee)
    )


def _invalid_attendance_statement():
    return (
        select(AttendanceModel, EmployeeModel)
        .join(UserModel, UserModel.id == AttendanceModel.user_id)
        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .where(
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            AttendanceModel.record_status == "INVALID",
        )
    )


class SqlAlchemyAttendanceReviewRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_invalid(
        self, supervisor_employee_id: Optional[UUID], today: date, actor_employee_id: Optional[UUID] = None
    ) -> list[ReviewableAttendanceRecord]:
        statement = _invalid_attendance_statement().order_by(
            AttendanceModel.work_date.desc(), EmployeeModel.employee_no
        )
        statement = statement.where(_review_scope(supervisor_employee_id, actor_employee_id, today))
        rows = (await self._session.execute(statement)).all()
        return [_record(attendance, employee) for attendance, employee in rows]

    async def lock_invalid(
        self, attendance_id: UUID, supervisor_employee_id: Optional[UUID], today: date,
        actor_employee_id: Optional[UUID] = None,
    ) -> Optional[ReviewableAttendanceRecord]:
        statement = (
            _invalid_attendance_statement()
            .with_for_update(of=AttendanceModel)
            .where(AttendanceModel.id == attendance_id)
        )
        statement = statement.where(_review_scope(supervisor_employee_id, actor_employee_id, today))
        row = (await self._session.execute(statement)).first()
        return _record(*row) if row is not None else None

    async def list_unresolved_routes(self) -> list[UnresolvedAttendanceRouting]:
        rows = (await self._session.execute(
            select(AttendanceModel, EmployeeModel, ApprovalRouteModel)
            .join(ApprovalRouteModel, ApprovalRouteModel.resource_id == AttendanceModel.id)
            .join(EmployeeModel, EmployeeModel.id == ApprovalRouteModel.employee_id)
            .where(
                ApprovalRouteModel.resource_type == "invalid_attendance",
                ApprovalRouteModel.routing_mode == "UNRESOLVED",
                ApprovalRouteModel.is_current.is_(True),
                AttendanceModel.record_status == "INVALID",
            )
            .order_by(AttendanceModel.work_date.desc(), EmployeeModel.employee_no)
        )).all()
        unresolved = []
        for attendance, employee, route in rows:
            if route.routing_error is None:
                raise RuntimeError("An unresolved attendance approval has no routing error.")
            unresolved.append(UnresolvedAttendanceRouting(_record(attendance, employee), route.routing_error))
        return unresolved

    async def retry_unresolved_route(self, attendance_id: UUID, actor_id: UUID, today: date) -> Optional[str]:
        row = (await self._session.execute(
            select(ApprovalRouteModel)
            .join(AttendanceModel, AttendanceModel.id == ApprovalRouteModel.resource_id)
            .where(
                AttendanceModel.id == attendance_id,
                AttendanceModel.record_status == "INVALID",
                ApprovalRouteModel.resource_type == "invalid_attendance",
                ApprovalRouteModel.routing_mode == "UNRESOLVED",
                ApprovalRouteModel.is_current.is_(True),
            )
            .with_for_update(of=(AttendanceModel, ApprovalRouteModel))
        )).scalar_one_or_none()
        if row is None:
            raise RecordNotFoundError("Unresolved attendance approval was not found or has already been routed.")
        if row.employee_id is None:
            raise ValueError("The unresolved attendance approval has no employee. Contact an administrator.")
        try:
            await assign_org_approval(
                self._session, resource_type="invalid_attendance", resource_id=attendance_id,
                employee_id=row.employee_id, assigned_by=actor_id, on_date=today,
                permission_code="attendance.read_team",
            )
        except ApprovalRoutingError as error:
            row.routing_error = str(error)
            await self._session.flush()
            return str(error)
        return None

    async def save_review(self, attendance: ReviewableAttendance) -> None:
        model = await self._session.get(AttendanceModel, attendance.id)
        model.record_status = attendance.record_status
        model.approved_by_id = attendance.approved_by_id
        model.approved_at = attendance.approved_at
        await self._session.flush()

    async def require_attendance_open(self, employee_id: UUID, work_date: date, now: datetime) -> None:
        await require_attendance_open(self._session, employee_id, work_date, work_date, now)
