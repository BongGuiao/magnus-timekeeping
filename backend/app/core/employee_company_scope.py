from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)


def _active_employee_company_query(
    user_id: UUID,
    current_date: date,
) -> Select[tuple[UUID]]:
    return (
        select(EmploymentAssignmentModel.company_id)
        .join(EmployeeModel, EmployeeModel.id == EmploymentAssignmentModel.employee_id)
        .join(UserModel, UserModel.employee_id == EmployeeModel.id)
        .where(
            UserModel.id == user_id,
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
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
    )


async def get_active_employee_company_ids(
    session: AsyncSession,
    user_id: UUID,
    current_date: date,
) -> list[UUID]:
    company_ids = await session.scalars(
        _active_employee_company_query(user_id, current_date)
        .distinct()
        .order_by(EmploymentAssignmentModel.company_id)
    )
    return list(company_ids)


async def get_latest_active_employee_company_id(
    session: AsyncSession,
    user_id: UUID,
    current_date: date,
) -> UUID | None:
    return await session.scalar(
        _active_employee_company_query(user_id, current_date)
        .order_by(
            EmploymentAssignmentModel.effective_from.desc(),
            EmploymentAssignmentModel.created_at.desc(),
            EmploymentAssignmentModel.id.desc(),
        )
        .limit(1)
    )
