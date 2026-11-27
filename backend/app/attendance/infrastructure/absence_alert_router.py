from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.infrastructure.absence_alert_models import AbsenceStreakAlertModel, AbsenceStreakDismissalModel
from app.auth.infrastructure.approval_routing import active_assignment_conditions
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel

router = APIRouter(prefix="/absence-alerts", tags=["Absence alerts"])
MANILA = ZoneInfo("Asia/Manila")


class AbsenceAlert(BaseModel):
    id: UUID
    employee_no: str
    employee_name: str
    absence_dates: list[date]
    created_at: datetime
    resolved_at: datetime | None


def _actor_id(claims: dict) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid user identity.") from error


async def _visible_alerts(session: AsyncSession, user_id: UUID, today: date):
    user = await session.scalar(select(UserModel).where(
        UserModel.id == user_id,
        UserModel.is_active.is_(True),
        UserModel.account_status == "ACTIVE",
    ))
    if user is None:
        raise HTTPException(status_code=403, detail="Your account is not active.")
    actor_employee_id = None
    if user.employee_id is not None:
        actor_employee_id = await session.scalar(select(EmployeeModel.id).where(
            EmployeeModel.id == user.employee_id,
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
        ))
    assignment = EmploymentAssignmentModel
    role_access = exists(select(UserRoleModel.id).join(
        RoleModel, RoleModel.id == UserRoleModel.role_id,
    ).where(
        UserRoleModel.user_id == user_id,
        UserRoleModel.effective_from <= today,
        or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= today),
        or_(UserRoleModel.company_id.is_(None), UserRoleModel.company_id == AbsenceStreakAlertModel.company_id),
        UserRoleModel.org_unit_id.is_(None),
        RoleModel.is_active.is_(True),
        RoleModel.role_code == "HR_ADMIN",
    ))
    manager_access = exists(select(assignment.id).outerjoin(
        OrgUnit, and_(
            OrgUnit.id == assignment.org_unit_id,
            OrgUnit.company_id == assignment.company_id,
            OrgUnit.is_active.is_(True), OrgUnit.status == "ACTIVE", OrgUnit.deleted_at.is_(None),
            OrgUnit.effective_from <= today,
            or_(OrgUnit.effective_to.is_(None), OrgUnit.effective_to >= today),
        ),
    ).where(
        assignment.employee_id == AbsenceStreakAlertModel.employee_id,
        assignment.company_id == AbsenceStreakAlertModel.company_id,
        *active_assignment_conditions(today),
        or_(assignment.supervisor_employee_id == actor_employee_id, OrgUnit.manager_employee_id == actor_employee_id),
    )) if actor_employee_id is not None else False
    own = AbsenceStreakAlertModel.employee_id == actor_employee_id if actor_employee_id is not None else False
    return or_(own, role_access, manager_access)


@router.get("", response_model=ResponseEnvelope[list[AbsenceAlert]])
async def list_absence_alerts(
    response: Response,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    response.headers["Cache-Control"] = "no-store"
    if not settings.ABSENCE_STREAK_ALERTS_ENABLED:
        return ResponseEnvelope(data=[])
    user_id = _actor_id(claims)
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        visibility = await _visible_alerts(active.session, user_id, datetime.now(MANILA).date())
        rows = (await active.session.execute(
            select(AbsenceStreakAlertModel, EmployeeModel)
            .join(EmployeeModel, EmployeeModel.id == AbsenceStreakAlertModel.employee_id)
            .where(
                visibility,
                ~exists(select(AbsenceStreakDismissalModel.alert_id).where(
                    AbsenceStreakDismissalModel.alert_id == AbsenceStreakAlertModel.id,
                    AbsenceStreakDismissalModel.user_id == user_id,
                )),
            )
            .order_by(AbsenceStreakAlertModel.created_at.desc(), AbsenceStreakAlertModel.id.desc())
        )).all()
        alerts = [
            AbsenceAlert(
                id=alert.id, employee_no=employee.employee_no,
                employee_name=" ".join(part for part in (employee.first_name, employee.last_name) if part),
                absence_dates=[alert.first_absence_date, alert.second_absence_date, alert.third_absence_date],
                created_at=alert.created_at, resolved_at=alert.resolved_at,
            )
            for alert, employee in rows
        ]
    return ResponseEnvelope(data=alerts)


@router.post("/{alert_id}/dismiss", response_model=ResponseEnvelope[bool])
async def dismiss_absence_alert(
    alert_id: UUID,
    response: Response,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    response.headers["Cache-Control"] = "no-store"
    if not settings.ABSENCE_STREAK_ALERTS_ENABLED:
        raise HTTPException(status_code=404, detail="Absence alerts are disabled.")
    user_id = _actor_id(claims)
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        visibility = await _visible_alerts(active.session, user_id, datetime.now(MANILA).date())
        found = await active.session.scalar(select(AbsenceStreakAlertModel.id).where(
            AbsenceStreakAlertModel.id == alert_id, visibility,
        ))
        if found is None:
            raise HTTPException(status_code=404, detail="Absence alert not found.")
        await active.session.execute(
            insert(AbsenceStreakDismissalModel).values(alert_id=alert_id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["alert_id", "user_id"])
        )
    return ResponseEnvelope(data=True)
