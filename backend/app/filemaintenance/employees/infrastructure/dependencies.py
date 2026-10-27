from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.application.related_use_case import (
    CreateEmployeeSkillUseCase,
    CreateEmploymentAssignmentsBatchUseCase,
    CreateEmploymentAssignmentUseCase,
    GetEmployeeSkillUseCase,
    GetEmploymentAssignmentUseCase,
    ListEmployeeSkillsUseCase,
    ListEmploymentAssignmentsUseCase,
    UpdateEmployeeSkillUseCase,
    UpdateEmploymentAssignmentUseCase,
)
from app.filemaintenance.employees.application.use_case import (
    CreateEmployeeUseCase,
    GetEmployeeUseCase,
    ListEmployeesUseCase,
    UpdateEmployeeUseCase,
)


def get_create_employee_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateEmployeeUseCase:
    return CreateEmployeeUseCase(uow)


def get_update_employee_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateEmployeeUseCase:
    return UpdateEmployeeUseCase(uow)


def get_employee_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetEmployeeUseCase:
    return GetEmployeeUseCase(uow)


def get_list_employees_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListEmployeesUseCase:
    return ListEmployeesUseCase(uow)


def get_create_assignment_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> CreateEmploymentAssignmentUseCase:
    return CreateEmploymentAssignmentUseCase(uow)


def get_create_assignments_batch_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateEmploymentAssignmentsBatchUseCase:
    return CreateEmploymentAssignmentsBatchUseCase(uow)


def get_update_assignment_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> UpdateEmploymentAssignmentUseCase:
    return UpdateEmploymentAssignmentUseCase(uow)


def get_assignment_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> GetEmploymentAssignmentUseCase:
    return GetEmploymentAssignmentUseCase(uow)


def get_list_assignments_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> ListEmploymentAssignmentsUseCase:
    return ListEmploymentAssignmentsUseCase(uow)


def get_create_skill_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> CreateEmployeeSkillUseCase:
    return CreateEmployeeSkillUseCase(uow)


def get_update_skill_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> UpdateEmployeeSkillUseCase:
    return UpdateEmployeeSkillUseCase(uow)


def get_skill_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> GetEmployeeSkillUseCase:
    return GetEmployeeSkillUseCase(uow)


def get_list_skills_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> ListEmployeeSkillsUseCase:
    return ListEmployeeSkillsUseCase(uow)
