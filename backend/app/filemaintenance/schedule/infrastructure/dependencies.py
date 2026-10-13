from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.schedule.application.employee_schedule_assignment_use_case import (
    ApproveEmployeeScheduleAssignmentUseCase,
    CreateEmployeeScheduleAssignmentUseCase,
    DeactivateEmployeeScheduleAssignmentUseCase,
    GetEmployeeScheduleAssignmentUseCase,
    ListEmployeeScheduleAssignmentsUseCase,
    UpdateEmployeeScheduleAssignmentUseCase,
)
from app.filemaintenance.schedule.application.rest_day_pattern_use_case import (
    CreateRestDayPatternUseCase,
    DeleteRestDayPatternUseCase,
    GetRestDayPatternUseCase,
    ListRestDayPatternsUseCase,
    UpdateRestDayPatternUseCase,
)
from app.filemaintenance.schedule.application.use_case import (
    CreateScheduleSegmentUseCase,
    CreateScheduleTemplateUseCase,
    DeleteScheduleSegmentUseCase,
    GetScheduleSegmentUseCase,
    GetScheduleTemplateUseCase,
    ListScheduleSegmentsUseCase,
    ListScheduleTemplatesUseCase,
    UpdateScheduleSegmentUseCase,
    UpdateScheduleTemplateUseCase,
)


def get_approve_employee_schedule_assignment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ApproveEmployeeScheduleAssignmentUseCase:
    return ApproveEmployeeScheduleAssignmentUseCase(uow)


def get_create_employee_schedule_assignment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateEmployeeScheduleAssignmentUseCase:
    return CreateEmployeeScheduleAssignmentUseCase(uow)


def get_deactivate_employee_schedule_assignment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeactivateEmployeeScheduleAssignmentUseCase:
    return DeactivateEmployeeScheduleAssignmentUseCase(uow)


def get_employee_schedule_assignment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetEmployeeScheduleAssignmentUseCase:
    return GetEmployeeScheduleAssignmentUseCase(uow)


def get_list_employee_schedule_assignments_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListEmployeeScheduleAssignmentsUseCase:
    return ListEmployeeScheduleAssignmentsUseCase(uow)


def get_update_employee_schedule_assignment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateEmployeeScheduleAssignmentUseCase:
    return UpdateEmployeeScheduleAssignmentUseCase(uow)


def get_create_rest_day_pattern_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateRestDayPatternUseCase:
    return CreateRestDayPatternUseCase(uow)


def get_delete_rest_day_pattern_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeleteRestDayPatternUseCase:
    return DeleteRestDayPatternUseCase(uow)


def get_get_rest_day_pattern_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetRestDayPatternUseCase:
    return GetRestDayPatternUseCase(uow)


def get_list_rest_day_patterns_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListRestDayPatternsUseCase:
    return ListRestDayPatternsUseCase(uow)


def get_update_rest_day_pattern_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateRestDayPatternUseCase:
    return UpdateRestDayPatternUseCase(uow)


def get_create_schedule_segment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateScheduleSegmentUseCase:
    return CreateScheduleSegmentUseCase(uow)


def get_create_schedule_template_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateScheduleTemplateUseCase:
    return CreateScheduleTemplateUseCase(uow)


def get_delete_schedule_segment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeleteScheduleSegmentUseCase:
    return DeleteScheduleSegmentUseCase(uow)


def get_get_schedule_segment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetScheduleSegmentUseCase:
    return GetScheduleSegmentUseCase(uow)


def get_get_schedule_template_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetScheduleTemplateUseCase:
    return GetScheduleTemplateUseCase(uow)


def get_list_schedule_templates_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListScheduleTemplatesUseCase:
    return ListScheduleTemplatesUseCase(uow)


def get_list_schedule_segments_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListScheduleSegmentsUseCase:
    return ListScheduleSegmentsUseCase(uow)


def get_update_schedule_segment_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateScheduleSegmentUseCase:
    return UpdateScheduleSegmentUseCase(uow)


def get_update_schedule_template_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateScheduleTemplateUseCase:
    return UpdateScheduleTemplateUseCase(uow)
