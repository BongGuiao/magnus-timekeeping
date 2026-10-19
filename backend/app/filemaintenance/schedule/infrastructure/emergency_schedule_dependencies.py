from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.schedule.application.emergency_schedule_use_cases import (
    ListEmergencyScheduleTemplatesUseCase,
    ListMyEmergencyScheduleRequestsUseCase,
    ListPendingEmergencyScheduleRequestsUseCase,
    ReviewEmergencyScheduleRequestUseCase,
    SubmitEmergencyScheduleRequestUseCase,
)


def get_list_emergency_schedule_templates_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListEmergencyScheduleTemplatesUseCase:
    return ListEmergencyScheduleTemplatesUseCase(uow)


def get_submit_emergency_schedule_request_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> SubmitEmergencyScheduleRequestUseCase:
    return SubmitEmergencyScheduleRequestUseCase(uow)


def get_list_my_emergency_schedule_requests_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListMyEmergencyScheduleRequestsUseCase:
    return ListMyEmergencyScheduleRequestsUseCase(uow)


def get_list_pending_emergency_schedule_requests_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListPendingEmergencyScheduleRequestsUseCase:
    return ListPendingEmergencyScheduleRequestsUseCase(uow)


def get_review_emergency_schedule_request_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ReviewEmergencyScheduleRequestUseCase:
    return ReviewEmergencyScheduleRequestUseCase(uow)
