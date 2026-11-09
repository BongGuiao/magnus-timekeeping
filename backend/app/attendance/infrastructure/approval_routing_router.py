from datetime import date, datetime
import logging
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.authorization import CurrentAuthorization
from app.auth.infrastructure.approval_routing import (
    ApprovalRoutingError, OrgUnitApprover, active_assignment_conditions,
    active_org_unit_manager_condition, assign_org_approval, save_approval_route,
)
from app.auth.infrastructure.approval_routing_model import ApprovalRouteModel
from app.auth.infrastructure.approval_resources import RESOURCE_MODELS, ResourceType
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case, get_current_user_claims, require_permission,
)
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.schedule.infrastructure.schedule_upload_db_model import ScheduleUploadBatchModel, ScheduleUploadBatchRowModel
from app.filemaintenance.schedule.infrastructure.schedule_upload_repository import SqlAlchemyScheduleUploadRepository
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import ScheduleUploadStateError


router = APIRouter(prefix="/approval-routing", tags=["Approval routing"])
MANILA = ZoneInfo("Asia/Manila")
logger = logging.getLogger(__name__)


class UnresolvedApprovalSchema(BaseModel):
    id: UUID
    resource_type: ResourceType
    resource_id: UUID
    employee_name: str
    employee_code: str
    routing_error: str
    created_at: datetime


class ApproverOption(BaseModel):
    employee_id: UUID
    label: str


class UnresolvedApprovalsSchema(BaseModel):
    records: list[UnresolvedApprovalSchema]
    approvers: list[ApproverOption]
    can_manage: bool


class RoutingRecoveryInput(BaseModel):
    approver_employee_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class RoutingRecoveryResult(BaseModel):
    routing_mode: Literal["ORG_UNIT", "UNRESOLVED"]
    routing_error: str | None


def _actor_id(claims: dict) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid user identity.") from error


def _session(active: GenUnitOfWork) -> AsyncSession:
    if active.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return active.session


async def _authorization(
    claims: dict = Depends(get_current_user_claims),
    use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> CurrentAuthorization:
    return await use_case.execute(_actor_id(claims))


@router.get("/unresolved", response_model=ResponseEnvelope[UnresolvedApprovalsSchema])
async def list_unresolved_approvals(
    claims: dict = Depends(get_current_user_claims),
    authorization: CurrentAuthorization = Depends(_authorization),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor_id = _actor_id(claims)
    can_manage = "employees.manage" in authorization.permission_codes
    records = []
    approvers = []
    async with uow as active:
        session = _session(active)
        for resource_type, (model, state_field, pending_state, _permission) in RESOURCE_MODELS.items():
            statement = (
                select(ApprovalRouteModel, EmployeeModel)
                .join(model, model.id == ApprovalRouteModel.resource_id)
                .join(EmployeeModel, EmployeeModel.id == ApprovalRouteModel.employee_id)
                .where(
                    ApprovalRouteModel.resource_type == resource_type,
                    ApprovalRouteModel.routing_mode == "UNRESOLVED",
                    ApprovalRouteModel.is_current.is_(True),
                    getattr(model, state_field) == pending_state,
                )
                .order_by(ApprovalRouteModel.created_at.desc()).limit(100)
            )
            if hasattr(model, "is_active"):
                statement = statement.where(model.is_active.is_(True))
            if not can_manage:
                ownership = ApprovalRouteModel.assigned_by == actor_id
                if authorization.employee_id is not None:
                    ownership = or_(ownership, ApprovalRouteModel.employee_id == authorization.employee_id)
                statement = statement.where(ownership)
            for route, employee in (await session.execute(statement)).all():
                if route.routing_error is None:
                    raise RuntimeError("An unresolved approval has no routing error.")
                records.append(UnresolvedApprovalSchema(
                    id=route.id, resource_type=resource_type, resource_id=route.resource_id,
                    employee_name=employee.preferred_name or f"{employee.first_name} {employee.last_name}",
                    employee_code=employee.employee_no, routing_error=route.routing_error, created_at=route.created_at,
                ))
        if can_manage:
            rows = (await session.execute(
                select(EmployeeModel)
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .where(
                    EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
                    UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
                    active_org_unit_manager_condition(EmployeeModel.id, datetime.now(MANILA).date(), approval_only=True),
                ).distinct().order_by(EmployeeModel.employee_no)
            )).scalars().all()
            approvers = [
                ApproverOption(employee_id=employee.id, label=f"{employee.employee_no} - {employee.first_name} {employee.last_name}")
                for employee in rows
            ]
    return ResponseEnvelope(status="success", data=UnresolvedApprovalsSchema(
        records=sorted(records, key=lambda record: record.created_at, reverse=True),
        approvers=approvers, can_manage=can_manage,
    ))


async def _manual_approver(
    session: AsyncSession, employee_ids: set[UUID], approver_id: UUID,
    excluded: set[UUID], today: date,
) -> OrgUnitApprover:
    if approver_id in employee_ids | excluded:
        raise ApprovalRoutingError("The approver must be independent of the requester, uploader, and assigning HR user.")
    account = await session.scalar(
        select(UserModel.id).join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .where(
            UserModel.employee_id == approver_id, UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
        )
    )
    if account is None:
        raise ApprovalRoutingError("The selected manager needs an active employee-linked account.")
    first_approver = None
    for employee_id in sorted(employee_ids):
        assignments = (await session.execute(
            select(EmploymentAssignmentModel.company_id, EmploymentAssignmentModel.org_unit_id)
            .where(EmploymentAssignmentModel.employee_id == employee_id, *active_assignment_conditions(today))
            .distinct()
        )).all()
        if len(assignments) != 1 or assignments[0][1] is None:
            raise ApprovalRoutingError("Correct the employee's current company and org unit assignment before assigning an approver.")
        company_id, source_id = assignments[0]
        source = await session.get(OrgUnit, source_id)
        if (
            source is None or source.company_id != company_id or source.deleted_at is not None
            or not source.is_active or source.status != "ACTIVE" or source.effective_from > today
            or (source.effective_to is not None and source.effective_to < today)
        ):
            raise ApprovalRoutingError("Correct the employee's inactive or invalid source org unit before assigning an approver.")
        ancestor_ids = {source_id}
        parent_id = source.parent_org_unit_id
        while parent_id is not None:
            if parent_id in ancestor_ids:
                raise ApprovalRoutingError("The organization hierarchy contains a cycle. Contact HR.")
            parent = await session.get(OrgUnit, parent_id)
            if parent is None or parent.company_id != company_id or parent.deleted_at is not None:
                raise ApprovalRoutingError("The organization hierarchy has an invalid company or parent. Contact HR.")
            ancestor_ids.add(parent_id)
            parent_id = parent.parent_org_unit_id
        manager_unit = await session.scalar(
            select(OrgUnit.id).where(
                OrgUnit.company_id == company_id, OrgUnit.manager_employee_id == approver_id,
                OrgUnit.manager_is_approver.is_(True),
                OrgUnit.excluded_approval_org_unit_ids.overlap(list(ancestor_ids)).is_(False),
                OrgUnit.deleted_at.is_(None), OrgUnit.is_active.is_(True), OrgUnit.status == "ACTIVE",
                OrgUnit.effective_from <= today,
                (OrgUnit.effective_to.is_(None) | (OrgUnit.effective_to >= today)),
            ).order_by(OrgUnit.id).limit(1)
        )
        if manager_unit is None:
            raise ApprovalRoutingError(
                "The selected approver must manage an active, approval-enabled org unit in every affected company "
                "without excluding the employee's org unit or its ancestors."
            )
        if first_approver is None:
            first_approver = OrgUnitApprover(approver_id, source_id, manager_unit)
    if first_approver is None:
        raise ApprovalRoutingError("No employees are linked to this approval.")
    return first_approver


@router.post("/{route_id}/recover", response_model=ResponseEnvelope[RoutingRecoveryResult])
async def recover_unresolved_approval(
    route_id: UUID, payload: RoutingRecoveryInput,
    claims: dict = Depends(require_permission("employees.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    if payload.approver_employee_id is not None and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="A reason is required to assign an exceptional independent approver.")
    async with uow as active:
        session = _session(active)
        route = await session.scalar(
            select(ApprovalRouteModel).where(ApprovalRouteModel.id == route_id).with_for_update()
        )
        if route is None or not route.is_current or route.routing_mode != "UNRESOLVED":
            raise HTTPException(status_code=409, detail="This approval is no longer unresolved. Refresh the alerts.")
        specification = RESOURCE_MODELS.get(route.resource_type)
        if specification is None:
            raise HTTPException(status_code=422, detail="This approval resource is not supported.")
        model, state_field, pending_state, permission = specification
        resource = await session.get(model, route.resource_id, with_for_update=True)
        if resource is None or getattr(resource, state_field) != pending_state or not getattr(resource, "is_active", True):
            raise HTTPException(status_code=409, detail="This request is no longer pending.")
        if route.employee_id is None:
            raise HTTPException(status_code=409, detail="The unresolved route has no employee.")
        today = datetime.now(MANILA).date()
        employee_ids = {route.employee_id}
        excluded = set()
        if isinstance(resource, ScheduleUploadBatchModel):
            employee_ids = set((await session.scalars(
                select(ScheduleUploadBatchRowModel.employee_id).where(ScheduleUploadBatchRowModel.batch_id == resource.id)
            )).all())
            uploader = await session.get(UserModel, resource.uploaded_by)
            if uploader and uploader.employee_id:
                excluded.add(uploader.employee_id)
        error_message = None
        try:
            if payload.approver_employee_id:
                actor = await session.get(UserModel, actor_id)
                if actor and actor.employee_id:
                    excluded.add(actor.employee_id)
                approver = await _manual_approver(session, employee_ids, payload.approver_employee_id, excluded, today)
                await save_approval_route(
                    session, resource_type=route.resource_type, resource_id=route.resource_id,
                    employee_id=route.employee_id, assigned_by=actor_id, approver=approver,
                )
            elif isinstance(resource, ScheduleUploadBatchModel):
                await SqlAlchemyScheduleUploadRepository(session).assign_batch_approver(
                    resource.id, employee_ids, resource.uploaded_by, today,
                )
                current = await session.scalar(select(ApprovalRouteModel).where(
                    ApprovalRouteModel.resource_type == route.resource_type,
                    ApprovalRouteModel.resource_id == route.resource_id, ApprovalRouteModel.is_current.is_(True),
                ))
                if current is None:
                    raise RuntimeError("Schedule routing did not save a current approval route.")
                error_message = current.routing_error
            else:
                await assign_org_approval(
                    session, resource_type=route.resource_type, resource_id=route.resource_id,
                    employee_id=route.employee_id, assigned_by=actor_id, on_date=today, permission_code=permission,
                )
        except (ApprovalRoutingError, ScheduleUploadStateError) as error:
            error_message = str(error)
            logger.warning("Approval route %s remains unresolved: %s", route_id, error_message)
            route.routing_error = error_message
            await session.flush()
        result = RoutingRecoveryResult(
            routing_mode="UNRESOLVED" if error_message else "ORG_UNIT", routing_error=error_message,
        )
        resource_type, resource_id = route.resource_type, route.resource_id
    await log_entity_action(
        es_client, user_id=actor_id, action="ASSIGN_APPROVER" if payload.approver_employee_id else "RETRY_ROUTING",
        resource=resource_type, resource_id=str(resource_id),
        after={**result.model_dump(), "approver_employee_id": str(payload.approver_employee_id) if payload.approver_employee_id else None,
               "reason": payload.reason},
    )
    return ResponseEnvelope(status="success", data=result)
