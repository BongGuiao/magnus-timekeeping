from elasticsearch import AsyncElasticsearch
from fastapi import Depends

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.core.generics.uow import get_unit_of_work, GenUnitOfWork
from app.attendance.application.admin_dashboard_use_cases import GetAdminDashboardUseCase
from app.attendance.application.attendance_review_use_cases import (
    ApproveInvalidAttendanceUseCase,
    ListInvalidAttendanceUseCase,
)
from app.attendance.application.authorized_location_use_cases import ListMyAttendanceLocationsUseCase
from app.attendance.application.punch_use_cases import (
    IssueDeviceChallengeUseCase,
    SubmitBreakPunchUseCase,
    SubmitClockPunchUseCase,
)
from app.attendance.application.recent_attendance_use_cases import GetRecentAttendanceSnapshotUseCase
from app.attendance.application.supervisor_attendance_location_use_cases import (
    ListSupervisorAttendanceLocationsUseCase,
    ListSupervisorTeamEmployeesUseCase,
)
from app.attendance.application.overtime_use_cases import (
    DecideOvertimeApplicationUseCase,
    GetOvertimeAttendanceOptionsUseCase,
    ListMyOvertimeApplicationsUseCase,
    ListPendingOvertimeApplicationsUseCase,
    RecalculateAttendanceRangeUseCase,
    SubmitOvertimeApplicationUseCase,
    UpdateOvertimeApplicationUseCase,
)
from app.attendance.application.use_case import (
    ClockAttendanceUseCase, 
    GetLastAttendanceUseCase, 
    RecordBreakUseCase,
)
from app.attendance.infrastructure.device_proof_adapter import DeviceChallengeProofService
from app.attendance.infrastructure.overtime_adapters import (
    CeleryRecentAttendanceRefresher,
    ElasticsearchAuditTrail,
)
from app.attendance.infrastructure.recent_attendance_adapters import (
    RedisRecentAttendanceSnapshotCache,
    TaskRecentAttendanceSnapshotLoader,
)
from app.attendance.infrastructure.unit_of_work import SqlAlchemyAttendanceUnitOfWork
from app.core import face_recognition_service

def get_record_break_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> RecordBreakUseCase:
    return RecordBreakUseCase(uow, face_recognition_service)


def get_clock_attendance_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> ClockAttendanceUseCase:
    return ClockAttendanceUseCase(uow, face_recognition_service)


def get_last_attendance_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> GetLastAttendanceUseCase:
    return GetLastAttendanceUseCase(uow)


def get_device_proof_service() -> DeviceChallengeProofService:
    return DeviceChallengeProofService(get_unit_of_work())


def get_issue_device_challenge_use_case(
    proofs: DeviceChallengeProofService = Depends(get_device_proof_service),
) -> IssueDeviceChallengeUseCase:
    return IssueDeviceChallengeUseCase(proofs)


def get_submit_clock_punch_use_case(
    clock: ClockAttendanceUseCase = Depends(get_clock_attendance_use_case),
    proofs: DeviceChallengeProofService = Depends(get_device_proof_service),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> SubmitClockPunchUseCase:
    return SubmitClockPunchUseCase(clock, proofs, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client))


def get_submit_break_punch_use_case(
    record_break: RecordBreakUseCase = Depends(get_record_break_use_case),
    proofs: DeviceChallengeProofService = Depends(get_device_proof_service),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> SubmitBreakPunchUseCase:
    return SubmitBreakPunchUseCase(record_break, proofs, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client))


def get_attendance_unit_of_work(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> SqlAlchemyAttendanceUnitOfWork:
    return SqlAlchemyAttendanceUnitOfWork(uow)


def get_overtime_attendance_options_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> GetOvertimeAttendanceOptionsUseCase:
    return GetOvertimeAttendanceOptionsUseCase(
        uow, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client),
    )


def get_recalculate_attendance_range_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> RecalculateAttendanceRangeUseCase:
    return RecalculateAttendanceRangeUseCase(
        uow, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client),
    )


def get_submit_overtime_application_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> SubmitOvertimeApplicationUseCase:
    return SubmitOvertimeApplicationUseCase(uow, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client))


def get_update_overtime_application_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> UpdateOvertimeApplicationUseCase:
    return UpdateOvertimeApplicationUseCase(uow, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client))


def get_list_my_overtime_applications_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> ListMyOvertimeApplicationsUseCase:
    return ListMyOvertimeApplicationsUseCase(uow)


def get_list_pending_overtime_applications_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> ListPendingOvertimeApplicationsUseCase:
    return ListPendingOvertimeApplicationsUseCase(uow)


def get_decide_overtime_application_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> DecideOvertimeApplicationUseCase:
    return DecideOvertimeApplicationUseCase(uow, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client))


def get_list_invalid_attendance_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> ListInvalidAttendanceUseCase:
    return ListInvalidAttendanceUseCase(uow)


def get_approve_invalid_attendance_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
) -> ApproveInvalidAttendanceUseCase:
    return ApproveInvalidAttendanceUseCase(uow, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client))


def get_list_my_attendance_locations_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> ListMyAttendanceLocationsUseCase:
    return ListMyAttendanceLocationsUseCase(uow)


def get_recent_attendance_snapshot_use_case() -> GetRecentAttendanceSnapshotUseCase:
    return GetRecentAttendanceSnapshotUseCase(
        TaskRecentAttendanceSnapshotLoader(), RedisRecentAttendanceSnapshotCache()
    )


def get_admin_dashboard_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> GetAdminDashboardUseCase:
    return GetAdminDashboardUseCase(uow)


def get_supervisor_attendance_locations_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> ListSupervisorAttendanceLocationsUseCase:
    return ListSupervisorAttendanceLocationsUseCase(uow)


def get_supervisor_team_employees_use_case(
    uow: SqlAlchemyAttendanceUnitOfWork = Depends(get_attendance_unit_of_work),
) -> ListSupervisorTeamEmployeesUseCase:
    return ListSupervisorTeamEmployeesUseCase(uow)
