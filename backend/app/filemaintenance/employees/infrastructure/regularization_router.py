from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel, EmploymentAssignmentModel, RegularizationNotificationModel,
)
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit

router = APIRouter(prefix="/regularization-review", tags=["Regularization Review"])
MANILA = ZoneInfo("Asia/Manila")


class RegularizationCandidate(BaseModel):
    assignment_id: UUID
    employee_id: UUID
    employee_no: str
    employee_name: str
    company_name: str
    org_unit_name: str | None
    employment_type: str
    hire_date: date
    six_month_date: date
    days_remaining: int


class RegularizationReview(BaseModel):
    as_of: date
    candidates: list[RegularizationCandidate]
    notification_pending: bool


class NotificationDismissal(BaseModel):
    notification_date: date


def six_month_date(hire_date: date) -> date:
    month_index = hire_date.year * 12 + hire_date.month - 1 + 6
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(hire_date.day, monthrange(year, month)[1]))


async def require_hr_admin(
    claims: dict = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> UUID:
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user identity.") from error
    authorization = await authorization_use_case.execute(user_id)
    if not any(role.strip().upper() == "HR_ADMIN" for role in authorization.role_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only HR administrators can review regularization.")
    return user_id


async def load_candidates(session: AsyncSession, today: date) -> list[RegularizationCandidate]:
    assignment = EmploymentAssignmentModel
    rows = (await session.execute(
        select(
            assignment.id.label("assignment_id"), assignment.employee_id, EmployeeModel.employee_no,
            EmployeeModel.first_name, EmployeeModel.middle_name, EmployeeModel.last_name,
            EmployeeModel.suffix, EmployeeModel.preferred_name, CompanyModel.legal_name,
            OrgUnit.org_unit_name, assignment.employment_type, assignment.hire_date,
        )
        .join(EmployeeModel, EmployeeModel.id == assignment.employee_id)
        .join(CompanyModel, CompanyModel.id == assignment.company_id)
        .outerjoin(OrgUnit, OrgUnit.id == assignment.org_unit_id)
        .where(
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            assignment.is_active.is_(True),
            assignment.status == "ACTIVE",
            assignment.effective_from <= today,
            or_(assignment.effective_to.is_(None), assignment.effective_to >= today),
            or_(assignment.separation_date.is_(None), assignment.separation_date >= today),
            assignment.hire_date <= today,
            func.upper(func.trim(assignment.employment_type)) != "REGULAR",
        )
    )).all()
    candidates = []
    for row in rows:
        due = six_month_date(row.hire_date)
        if today < due - timedelta(days=15):
            continue
        name = (row.preferred_name or "").strip() or " ".join(
            part for part in (row.first_name, row.middle_name, row.last_name, row.suffix) if part
        )
        candidates.append(RegularizationCandidate(
            assignment_id=row.assignment_id, employee_id=row.employee_id,
            employee_no=row.employee_no, employee_name=name, company_name=row.legal_name,
            org_unit_name=row.org_unit_name, employment_type=row.employment_type,
            hire_date=row.hire_date, six_month_date=due, days_remaining=(due - today).days,
        ))
    candidates.sort(key=lambda candidate: (candidate.six_month_date, candidate.employee_no, str(candidate.assignment_id)))
    return candidates


@router.post("", response_model=ResponseEnvelope[RegularizationReview])
async def get_regularization_review(
    response: Response,
    user_id: UUID = Depends(require_hr_admin),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    today = datetime.now(MANILA).date()
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        candidates = await load_candidates(session, today)
        pending = False
        if candidates:
            await session.execute(
                insert(RegularizationNotificationModel)
                .values(user_id=user_id, notification_date=today)
                .on_conflict_do_nothing(index_elements=["user_id", "notification_date"])
            )
            notification = await session.get(RegularizationNotificationModel, (user_id, today))
            if notification is None:
                raise RuntimeError("The daily regularization notification could not be loaded.")
            pending = notification.dismissed_at is None
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(data=RegularizationReview(as_of=today, candidates=candidates, notification_pending=pending))


@router.post("/dismiss", response_model=ResponseEnvelope[bool])
async def dismiss_regularization_notification(
    payload: NotificationDismissal,
    response: Response,
    user_id: UUID = Depends(require_hr_admin),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    if payload.notification_date != datetime.now(MANILA).date():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The notification date has changed. Refresh the dashboard.")
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        result = await session.execute(
            update(RegularizationNotificationModel)
            .where(
                RegularizationNotificationModel.user_id == user_id,
                RegularizationNotificationModel.notification_date == payload.notification_date,
            )
            .values(dismissed_at=func.coalesce(RegularizationNotificationModel.dismissed_at, datetime.now(timezone.utc)))
            .returning(RegularizationNotificationModel.user_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The daily notification was not found.")
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(data=True)
