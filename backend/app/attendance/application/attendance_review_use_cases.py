from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional
from uuid import UUID

from app.attendance.application.attendance_review_ports import AttendanceReviewUnitOfWork
from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.ports import AuditTrail, RecentAttendanceRefresher
from app.attendance.domain.entities.attendance_review import ReviewableAttendanceRecord
from app.attendance.domain.exceptions import RecordNotFoundError
from app.core.generics.uc_base import BaseUseCase


@dataclass
class ListInvalidAttendanceInput:
    """supervisor_employee_id is None for administrators, who review every team."""

    supervisor_employee_id: Optional[UUID]


class ListInvalidAttendanceUseCase(BaseUseCase[list[ReviewableAttendanceRecord]]):
    def __init__(self, uow: AttendanceReviewUnitOfWork, clock: Callable[[], datetime] = utc_now):
        self._uow = uow
        self._clock = clock

    async def _execute(self, data: ListInvalidAttendanceInput) -> list[ReviewableAttendanceRecord]:
        async with self._uow as uow:
            return await uow.review.list_invalid(data.supervisor_employee_id, ph_today(self._clock()))


@dataclass
class ApproveInvalidAttendanceInput:
    attendance_id: UUID
    actor_id: UUID
    supervisor_employee_id: Optional[UUID]


class ApproveInvalidAttendanceUseCase(BaseUseCase[ReviewableAttendanceRecord]):
    def __init__(
        self,
        uow: AttendanceReviewUnitOfWork,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._uow = uow
        self._refresher = refresher
        self._audit = audit
        self._clock = clock

    async def _execute(self, data: ApproveInvalidAttendanceInput) -> ReviewableAttendanceRecord:
        now = self._clock()
        async with self._uow as uow:
            record = await uow.review.lock_invalid(
                data.attendance_id, data.supervisor_employee_id, ph_today(now)
            )
            if record is None:
                raise RecordNotFoundError(
                    "Invalid attendance was not found for your assigned employees or has already been reviewed."
                )
            record.attendance.approve(data.actor_id, now)
            await uow.review.save_review(record.attendance)

        self._refresher.request_refresh(record.attendance.user_id)
        await self._audit.record(
            user_id=data.actor_id,
            action="APPROVE",
            resource="attendance",
            resource_id=str(data.attendance_id),
            after={"record_status": "VALID", "approved_at": now.isoformat()},
        )
        return record
