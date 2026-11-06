from dataclasses import dataclass
from datetime import date
import logging
from uuid import UUID

from sqlalchemy import and_, exists, false, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.auth.infrastructure.approval_routing_model import ApprovalRouteModel
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel


# Approval rights that come from being an active org-unit manager rather than from a role grant.
ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS = frozenset({
    "overtime.approve_team",
    "leave.approve_team",
    "official_business.approve_team",
    "schedule.approve_emergency",
    "attendance.approve_corrections_team",
    "attendance.read_team",
    "schedule.approve",
})
logger = logging.getLogger(__name__)


class ApprovalRoutingError(ValueError):
    """The organization is not configured for a safe approval assignment."""


@dataclass(frozen=True)
class OrgUnitApprover:
    employee_id: UUID
    source_org_unit_id: UUID
    approver_org_unit_id: UUID


def active_assignment_conditions(on_date: date | ColumnElement[date]) -> tuple[ColumnElement[bool], ...]:
    assignment = EmploymentAssignmentModel
    return (
        assignment.is_active.is_(True),
        assignment.status == "ACTIVE",
        assignment.effective_from <= on_date,
        or_(assignment.effective_to.is_(None), assignment.effective_to >= on_date),
        or_(assignment.separation_date.is_(None), assignment.separation_date >= on_date),
    )


def legacy_supervisor_scope(
    employee_id: ColumnElement[UUID],
    supervisor_employee_id: UUID,
    on_date: date | ColumnElement[date],
) -> ColumnElement[bool]:
    assignment = EmploymentAssignmentModel
    return exists(
        select(assignment.id).where(
            assignment.employee_id == employee_id,
            assignment.supervisor_employee_id == supervisor_employee_id,
            *active_assignment_conditions(on_date),
        )
    )


def active_org_unit_manager_condition(
    manager_employee_id: UUID | ColumnElement[UUID],
    on_date: date | ColumnElement[date],
) -> ColumnElement[bool]:
    return exists(
        select(OrgUnit.id).where(
            OrgUnit.manager_employee_id == manager_employee_id,
            OrgUnit.deleted_at.is_(None),
            OrgUnit.is_active.is_(True),
            OrgUnit.status == "ACTIVE",
            OrgUnit.effective_from <= on_date,
            or_(OrgUnit.effective_to.is_(None), OrgUnit.effective_to >= on_date),
        )
    )


async def resolve_org_unit_approver(
    session: AsyncSession,
    employee_id: UUID,
    on_date: date,
    permission_code: str | None,
    *,
    excluded_employee_ids: frozenset[UUID] = frozenset(),
) -> OrgUnitApprover:
    assignments = (
        await session.execute(
            select(EmploymentAssignmentModel.company_id, EmploymentAssignmentModel.org_unit_id)
            .where(
                EmploymentAssignmentModel.employee_id == employee_id,
                *active_assignment_conditions(on_date),
            )
            .distinct()
        )
    ).all()
    if not assignments:
        raise ApprovalRoutingError("No current employment assignment exists. Contact HR.")
    if len(assignments) != 1:
        raise ApprovalRoutingError("Multiple current organization assignments exist. Contact HR.")
    company_id, source_unit_id = assignments[0]
    if source_unit_id is None:
        raise ApprovalRoutingError("No organization unit is assigned. Contact HR.")

    excluded = excluded_employee_ids | {employee_id}
    visited: set[UUID] = set()
    unit_id: UUID | None = source_unit_id
    parent_requested = False
    while unit_id is not None:
        if unit_id in visited:
            raise ApprovalRoutingError("The organization hierarchy contains a cycle. Contact HR.")
        visited.add(unit_id)
        unit = await session.get(OrgUnit, unit_id)
        if unit is None or unit.company_id != company_id:
            raise ApprovalRoutingError("The organization hierarchy has an invalid company or parent. Contact HR.")
        if (
            unit.deleted_at is not None
            or not unit.is_active
            or unit.status != "ACTIVE"
            or unit.effective_from > on_date
            or (unit.effective_to is not None and unit.effective_to < on_date)
        ):
            raise ApprovalRoutingError("An organization unit in the approval hierarchy is not active. Contact HR.")

        manager_id = unit.manager_employee_id
        if manager_id is None:
            raise ApprovalRoutingError("The organization unit has no manager. HR must assign an independent approver.")
        if manager_id in excluded:
            if parent_requested:
                raise ApprovalRoutingError("The parent manager is not an independent approver. Contact HR.")
            parent_requested = True
            unit_id = unit.parent_org_unit_id
            continue
        if manager_id is not None and manager_id not in excluded:
            if permission_code is None:
                active_manager = await session.scalar(
                    select(EmployeeModel.id).where(
                        EmployeeModel.id == manager_id,
                        EmployeeModel.is_active.is_(True),
                        EmployeeModel.record_status == "ACTIVE",
                    )
                )
                if active_manager is None:
                    raise ApprovalRoutingError("The organization manager needs an active employee profile. Contact HR.")
            else:
                account = (
                    await session.execute(
                        select(UserModel.id)
                        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
                        .where(
                            EmployeeModel.id == manager_id,
                            EmployeeModel.is_active.is_(True),
                            EmployeeModel.record_status == "ACTIVE",
                            UserModel.is_active.is_(True),
                            UserModel.account_status == "ACTIVE",
                        )
                    )
                ).scalar_one_or_none()
                if account is None:
                    raise ApprovalRoutingError("The organization manager needs an active employee-linked account. Contact HR.")
                has_permission = permission_code in ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS or await session.scalar(
                    select(
                        exists(
                            select(UserRoleModel.id)
                            .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                            .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
                            .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
                            .where(
                                UserRoleModel.user_id == account,
                                UserRoleModel.effective_from <= on_date,
                                or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= on_date),
                                RoleModel.is_active.is_(True),
                                RolePermissionModel.allowed.is_(True),
                                PermissionModel.is_active.is_(True),
                                PermissionModel.permission_code == permission_code,
                            )
                        )
                    )
                )
                if not has_permission:
                    raise ApprovalRoutingError(
                        "The organization manager does not have the required approval permission. Contact HR."
                    )
            return OrgUnitApprover(manager_id, source_unit_id, unit.id)
        unit_id = unit.parent_org_unit_id

    raise ApprovalRoutingError("No eligible organization manager is configured. Contact HR.")


async def save_approval_route(
    session: AsyncSession,
    *,
    resource_type: str,
    resource_id: UUID,
    assigned_by: UUID | None,
    employee_id: UUID | None,
    approver: OrgUnitApprover | None,
    routing_error: str | None = None,
) -> None:
    if (approver is None) == (routing_error is None):
        raise ValueError("An approval route must have either an approver or a routing error.")
    await session.execute(
        update(ApprovalRouteModel)
        .where(
            ApprovalRouteModel.resource_type == resource_type,
            ApprovalRouteModel.resource_id == resource_id,
            ApprovalRouteModel.is_current.is_(True),
        )
        .values(is_current=False)
    )
    session.add(
        ApprovalRouteModel(
            resource_type=resource_type,
            resource_id=resource_id,
            routing_mode="ORG_UNIT" if approver is not None else "UNRESOLVED",
            employee_id=employee_id,
            source_org_unit_id=approver.source_org_unit_id if approver and employee_id else None,
            approver_org_unit_id=approver.approver_org_unit_id if approver and employee_id else None,
            approver_employee_id=approver.employee_id if approver else None,
            assigned_by=assigned_by,
            routing_error=routing_error,
        )
    )
    await session.flush()


async def assign_org_approval(
    session: AsyncSession,
    *,
    resource_type: str,
    resource_id: UUID,
    employee_id: UUID,
    assigned_by: UUID | None,
    on_date: date,
    permission_code: str,
    excluded_employee_ids: frozenset[UUID] = frozenset(),
    hold_unresolved: bool = False,
) -> OrgUnitApprover | None:
    try:
        approver = await resolve_org_unit_approver(
            session, employee_id, on_date, permission_code, excluded_employee_ids=excluded_employee_ids
        )
    except ApprovalRoutingError as error:
        if not hold_unresolved:
            raise
        logger.warning("Approval routing requires HR attention for %s %s: %s", resource_type, resource_id, error)
        await save_approval_route(
            session, resource_type=resource_type, resource_id=resource_id,
            employee_id=employee_id, assigned_by=assigned_by, approver=None, routing_error=str(error),
        )
        return None
    await save_approval_route(
        session,
        resource_type=resource_type,
        resource_id=resource_id,
        assigned_by=assigned_by,
        employee_id=employee_id,
        approver=approver,
    )
    return approver


def approval_route_scope(
    resource_type: str,
    resource_id: ColumnElement[UUID],
    reviewer_employee_id: UUID | None,
    legacy_scope: ColumnElement[bool],
) -> ColumnElement[bool]:
    route = ApprovalRouteModel
    current_route = (
        route.resource_type == resource_type,
        route.resource_id == resource_id,
        route.is_current.is_(True),
    )
    assigned = (
        exists(select(route.id).where(
            *current_route,
            route.routing_mode == "ORG_UNIT",
            route.approver_employee_id == reviewer_employee_id,
        ))
        if reviewer_employee_id is not None
        else false()
    )
    legacy = exists(select(route.id).where(*current_route, route.routing_mode == "LEGACY"))
    return or_(assigned, and_(legacy, legacy_scope))
