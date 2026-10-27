from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import or_, select

from app.auth.application.accounts import (
    DEFAULT_EMPLOYEE_PASSWORD,
    create_user_account,
    find_user_conflict,
    sync_user_account_with_employee,
)
from app.auth.domain.entities.user import AccountStatus, DEFAULT_EMPLOYEE_ROLE_CODE
from app.core.security import get_password_hash
from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)

MANILA_TIMEZONE = ZoneInfo("Asia/Manila")

def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized_payload = payload.copy()

    birth_date = normalized_payload.get("birth_date")
    if isinstance(birth_date, str):
        normalized_payload["birth_date"] = date.fromisoformat(birth_date) if birth_date else None

    for field in ("id", "created_by", "updated_by"):
        value = normalized_payload.get(field)
        if isinstance(value, str):
            normalized_payload[field] = UUID(value)

    return normalized_payload


_email_adapter = TypeAdapter(EmailStr)


def _validate_account_email(personal_email: Any, action: str) -> str:
    try:
        return str(_email_adapter.validate_python(personal_email)).strip().lower()
    except (ValidationError, TypeError) as error:
        raise ValueError(
            f"A valid personal email is required to {action} the employee account."
        ) from error


class CreateEmployeeUseCase(BaseUseCase[EmployeeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> EmployeeEntity:
        async with self.uow as uow:
            normalized_payload = _normalize_payload(payload)
            employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            existing = await employee_repo.find_one(
                EmployeeModel.employee_no == normalized_payload.get("employee_no")
            )
            if existing is not None:
                raise ValueError("Employee number already exists.")

            email = _validate_account_email(normalized_payload.get("personal_email"), "create")

            employee_no = str(normalized_payload.get("employee_no") or "").strip()
            if await find_user_conflict(uow, username=employee_no, email=email, employee_id=None):
                raise ValueError(
                    "An account already exists for this employee number or personal email."
                )

            employee = await employee_repo.add(normalized_payload)
            if employee.id is None:
                raise RuntimeError("Created employee profile has no ID.")

            is_employee_active = employee.is_active and employee.record_status == "ACTIVE"
            await create_user_account(
                uow,
                employee=employee,
                email=email,
                password_hash=get_password_hash(DEFAULT_EMPLOYEE_PASSWORD),
                role_code=DEFAULT_EMPLOYEE_ROLE_CODE,
                account_status=AccountStatus.ACTIVE if is_employee_active else AccountStatus.DISABLED,
                actor_id=employee.created_by,
                password_set_by_user=False,
            )
            return employee


def direct_report_conditions(supervisor_employee_id: UUID, current_date: date) -> tuple:
    """Same 'current direct report' rule used by supervisor attendance views."""
    return (
        EmployeeModel.id.in_(
            select(EmploymentAssignmentModel.employee_id).where(
                EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= current_date,
                or_(
                    EmploymentAssignmentModel.effective_to.is_(None),
                    EmploymentAssignmentModel.effective_to >= current_date,
                ),
                or_(
                    EmploymentAssignmentModel.separation_date.is_(None),
                    EmploymentAssignmentModel.separation_date >= current_date,
                ),
            )
        ),
    )


def _manila_today() -> date:
    return datetime.now(MANILA_TIMEZONE).date()


class GetEmployeeUseCase(BaseUseCase[EmployeeEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        employee_id: UUID,
        supervisor_employee_id: UUID | None = None,
    ) -> EmployeeEntity | None:
        criteria = [EmployeeModel.id == employee_id]
        if supervisor_employee_id is not None:
            criteria.extend(direct_report_conditions(supervisor_employee_id, _manila_today()))
        async with self.uow as uow:
            repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            return await repo.find_one(*criteria)


class ListEmployeesUseCase(BaseUseCase[list[EmployeeEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        supervisor_employee_id: UUID | None = None,
    ) -> list[EmployeeEntity]:
        criteria = []
        if supervisor_employee_id is not None:
            criteria.extend(direct_report_conditions(supervisor_employee_id, _manila_today()))
        async with self.uow as uow:
            repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            return await repo.find_all(
                *criteria,
                order_by=EmployeeModel.employee_no,
                offset=0,
                limit=1000,
            )


class UpdateEmployeeUseCase(BaseUseCase[EmployeeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, employee_id: UUID, payload: dict[str, Any]) -> EmployeeEntity:
        async with self.uow as uow:
            repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            existing = await repo.find_one(EmployeeModel.id == employee_id)
            if existing is None:
                raise ValueError("Employee not found.")

            entity_data = GenericMapper.to_entity(_normalize_payload(payload), EmployeeEntity)
            entity_data.id = employee_id
            changes = {
                key: value for key, value in entity_data.__dict__.items()
                if key not in ("id", "created_at", "created_by", "row_version", "updated_at", "updated_by")
            }
            updated = replace(
                existing,
                **changes,
                updated_at=entity_data.updated_at or existing.updated_at,
                updated_by=entity_data.updated_by or existing.updated_by,
                row_version=(existing.row_version or 0) + 1,
            )
            email = _validate_account_email(updated.personal_email, "update")
            saved = await repo.update(updated)
            await sync_user_account_with_employee(
                uow,
                employee=saved,
                email=email,
                actor_id=entity_data.updated_by,
                default_password_hash=get_password_hash(DEFAULT_EMPLOYEE_PASSWORD),
                default_role_code=DEFAULT_EMPLOYEE_ROLE_CODE,
            )
            return saved
