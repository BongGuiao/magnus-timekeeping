from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)


async def get_active_employee_company_ids(
    session: AsyncSession,
    user_id: UUID,
    current_date: date,
) -> list[UUID]:
    company_ids = await session.scalars(
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
        .distinct()
        .order_by(EmploymentAssignmentModel.company_id)
    )
    return list(company_ids)
