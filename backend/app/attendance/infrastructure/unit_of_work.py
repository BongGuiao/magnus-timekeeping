from app.attendance.infrastructure.admin_dashboard_repository import SqlAlchemyAdminDashboardRepository
from app.attendance.infrastructure.attendance_review_repository import SqlAlchemyAttendanceReviewRepository
from app.attendance.infrastructure.authorized_location_repository import SqlAlchemyAuthorizedLocationRepository
from app.attendance.infrastructure.overtime_repository import SqlAlchemyOvertimeRepository
from app.attendance.infrastructure.supervisor_attendance_location_repository import (
    SqlAlchemySupervisorAttendanceLocationRepository,
)
from app.core.generics.uow import GenUnitOfWork


class SqlAlchemyAttendanceUnitOfWork:
    """Adapts the generic unit of work to the attendance use cases' unit-of-work ports."""

    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow
        self.overtime: SqlAlchemyOvertimeRepository
        self.review: SqlAlchemyAttendanceReviewRepository
        self.locations: SqlAlchemyAuthorizedLocationRepository
        self.dashboard: SqlAlchemyAdminDashboardRepository
        self.team_locations: SqlAlchemySupervisorAttendanceLocationRepository

    async def __aenter__(self) -> "SqlAlchemyAttendanceUnitOfWork":
        active = await self._uow.__aenter__()
        self.overtime = SqlAlchemyOvertimeRepository(active.session)
        self.review = SqlAlchemyAttendanceReviewRepository(active.session)
        self.locations = SqlAlchemyAuthorizedLocationRepository(active.session)
        self.dashboard = SqlAlchemyAdminDashboardRepository(active.session)
        self.team_locations = SqlAlchemySupervisorAttendanceLocationRepository(active.session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._uow.__aexit__(exc_type, exc_val, exc_tb)
