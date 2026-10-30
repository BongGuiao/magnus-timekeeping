"""Seed the initial company and access-control catalog.

Revision ID: 71c39a5d02ab
Revises: 524d53624136
"""
from typing import Sequence, Union

from alembic import op

revision: str = "71c39a5d02ab"
down_revision: Union[str, None] = "524d53624136"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            INSERT INTO core.companies (company_code, legal_name)
            VALUES ('XYZ', 'XYZ Company')
            ON CONFLICT (company_code) DO NOTHING;

            INSERT INTO identity.roles (
                role_code, role_name, description, scope_type, is_system_role
            )
            VALUES
                ('SYSTEM_ADMIN', 'System Administrator', 'System-wide administration.', 'GLOBAL', true),
                ('SYSTEM_ADMINISTRATOR', 'System Administrator', 'System-wide administration.', 'GLOBAL', true),
                ('HR_ADMIN', 'HR Administrator', 'Human resources and payroll administration.', 'GLOBAL', true),
                ('MANAGER', 'Manager', 'Organization-level manager access.', 'ORG_UNIT', true),
                ('SUPERVISOR', 'Supervisor', 'Team-level supervisor access.', 'ORG_UNIT', true),
                ('EMPLOYEE', 'Employee', 'Self-service employee access.', 'COMPANY', true),
                ('PAYROLL_HEAD', 'Payroll Head', 'Payroll approval access.', 'COMPANY', true)
            ON CONFLICT (role_code) DO NOTHING;

            INSERT INTO identity.permissions (
                permission_code, module_code, action_code, permission_name, description
            )
            VALUES
                ('attendance.read_own', 'attendance', 'read_own', 'View own attendance', 'View attendance records belonging to the signed-in employee.'),
                ('attendance.read_team', 'attendance', 'read_team', 'View team attendance', 'View attendance within the supervisor team scope.'),
                ('attendance.read_org', 'attendance', 'read_org', 'View organization attendance', 'View attendance within the manager organization scope.'),
                ('attendance.finalize', 'attendance', 'finalize', 'Finalize attendance cutoff', 'Finalize reviewed attendance for a payroll cutoff before payroll calculation.'),
                ('leave.read_own', 'leave', 'read_own', 'View own leave', 'View leave requests belonging to the signed-in employee.'),
                ('leave.submit', 'leave', 'submit', 'Submit leave', 'Submit leave requests for the signed-in employee.'),
                ('leave.approve_team', 'leave', 'approve_team', 'Approve team leave', 'Review and approve leave within the assigned team scope.'),
                ('leave.manage', 'leave', 'manage', 'Manage leave administration', 'Manage leave types, balances, and HR leave records.'),
                ('overtime.submit_own', 'overtime', 'submit_own', 'Submit own overtime', 'Submit overtime requests for the signed-in employee.'),
                ('overtime.approve_team', 'overtime', 'approve_team', 'Approve team overtime', 'Review overtime within the assigned team scope.'),
                ('official_business.submit_own', 'official_business', 'submit_own', 'Submit own official business', 'Submit official-business requests for the signed-in employee.'),
                ('official_business.approve_team', 'official_business', 'approve_team', 'Approve team official business', 'Review requests within the assigned team scope.'),
                ('employees.read', 'employees', 'read', 'View employees', 'View employee records within the authorized organizational scope.'),
                ('employees.read_team', 'employees', 'read_team', 'View team employees', 'View employee records of current direct reports only.'),
                ('employees.manage', 'employees', 'manage', 'Manage employees', 'Create and update employee records.'),
                ('company.setup', 'company', 'setup', 'Manage company setup', 'Manage company and organization configuration.'),
                ('payroll.manage', 'payroll', 'manage', 'Manage payroll setup', 'Manage payroll groups, cutoffs, and related configuration.'),
                ('payroll.read_own', 'payroll', 'read_own', 'View own payroll cutoff results', 'View and acknowledge payroll cutoff calculations belonging to the signed-in employee.'),
                ('payroll.acknowledge_team', 'payroll', 'acknowledge_team', 'Acknowledge team payroll calculations', 'View and acknowledge payroll cutoff calculations for directly assigned employees.'),
                ('payroll.approve', 'payroll', 'approve', 'Approve and finalize payroll', 'Approve calculated payroll cutoffs after all employee results are ready.'),
                ('payroll.company_parameters.manage', 'payroll', 'company_parameters_manage', 'Manage company payroll parameters', 'Manage company-scoped payroll calculation and statutory deduction settings.'),
                ('schedule.manage', 'schedule', 'manage', 'Manage schedule setup', 'Manage schedule and rest-day configuration.'),
                ('schedule.upload_team', 'schedule', 'upload_team', 'Upload team schedules', 'Upload CSV schedule assignments for directly assigned employees, subject to approval.'),
                ('schedule.approve', 'schedule', 'approve', 'Approve uploaded schedules', 'Review, approve, or reject schedule upload batches submitted by supervisors.'),
                ('schedule.read_own', 'schedule', 'read_own', 'View own schedule', 'View current and upcoming approved schedule assignments of the signed-in employee.'),
                ('schedule.request_emergency', 'schedule', 'request_emergency', 'Request emergency schedule change', 'Request a one-day emergency schedule replacement for supervisor approval.'),
                ('schedule.approve_emergency', 'schedule', 'approve_emergency', 'Approve emergency schedule changes', 'Review one-day emergency schedule replacements for directly assigned employees.'),
                ('roles.manage', 'roles', 'manage', 'Manage roles and permissions', 'Manage role definitions, assignments, and permission grants.'),
                ('system.manage', 'system', 'manage', 'Manage system configuration', 'Manage system-wide configuration and administration.')
            ON CONFLICT (permission_code) DO NOTHING;

            WITH role_grants (role_code, permission_code) AS (
                SELECT upper(role_row.role_code), permission.permission_code
                FROM identity.roles AS role_row
                CROSS JOIN identity.permissions AS permission
                WHERE upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR')
                  AND permission.is_active
                  AND permission.permission_code NOT LIKE 'payroll.%'
                UNION ALL
                SELECT *
                FROM (VALUES
                ('HR_ADMIN', 'attendance.read_org'),
                ('HR_ADMIN', 'attendance.finalize'),
                ('HR_ADMIN', 'leave.read_own'),
                ('HR_ADMIN', 'leave.manage'),
                ('HR_ADMIN', 'employees.read'),
                ('HR_ADMIN', 'employees.manage'),
                ('HR_ADMIN', 'company.setup'),
                ('HR_ADMIN', 'payroll.manage'),
                ('HR_ADMIN', 'payroll.approve'),
                ('HR_ADMIN', 'payroll.company_parameters.manage'),
                ('HR_ADMIN', 'schedule.manage'),
                ('HR_ADMIN', 'schedule.approve'),
                ('HR_ADMIN', 'schedule.read_own'),
                ('HR_ADMIN', 'schedule.request_emergency'),
                ('MANAGER', 'attendance.read_own'),
                ('MANAGER', 'attendance.read_team'),
                ('MANAGER', 'attendance.read_org'),
                ('MANAGER', 'leave.read_own'),
                ('MANAGER', 'leave.approve_team'),
                ('MANAGER', 'overtime.approve_team'),
                ('MANAGER', 'official_business.approve_team'),
                ('MANAGER', 'employees.read'),
                ('MANAGER', 'payroll.read_own'),
                ('MANAGER', 'payroll.acknowledge_team'),
                ('MANAGER', 'schedule.upload_team'),
                ('MANAGER', 'schedule.read_own'),
                ('MANAGER', 'schedule.request_emergency'),
                ('MANAGER', 'schedule.approve_emergency'),
                ('SUPERVISOR', 'attendance.read_own'),
                ('SUPERVISOR', 'attendance.read_team'),
                ('SUPERVISOR', 'leave.read_own'),
                ('SUPERVISOR', 'leave.approve_team'),
                ('SUPERVISOR', 'overtime.approve_team'),
                ('SUPERVISOR', 'official_business.approve_team'),
                ('SUPERVISOR', 'employees.read_team'),
                ('SUPERVISOR', 'payroll.read_own'),
                ('SUPERVISOR', 'payroll.acknowledge_team'),
                ('SUPERVISOR', 'schedule.upload_team'),
                ('SUPERVISOR', 'schedule.read_own'),
                ('SUPERVISOR', 'schedule.request_emergency'),
                ('SUPERVISOR', 'schedule.approve_emergency'),
                ('EMPLOYEE', 'attendance.read_own'),
                ('EMPLOYEE', 'leave.read_own'),
                ('EMPLOYEE', 'leave.submit'),
                ('EMPLOYEE', 'overtime.submit_own'),
                ('EMPLOYEE', 'official_business.submit_own'),
                ('EMPLOYEE', 'payroll.read_own'),
                ('EMPLOYEE', 'schedule.read_own'),
                ('EMPLOYEE', 'schedule.request_emergency'),
                ('PAYROLL_HEAD', 'payroll.approve')
                ) AS proposed(role_code, permission_code)
            )
            INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
            SELECT role_row.id, permission_row.id, true
            FROM role_grants AS role_grant
            JOIN identity.roles AS role_row
              ON upper(role_row.role_code) = role_grant.role_code
            JOIN identity.permissions AS permission_row
              ON permission_row.permission_code = role_grant.permission_code
            WHERE permission_row.is_active
            ON CONFLICT (role_id, permission_id) DO NOTHING;
        END
        $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "The initial seed migration is irreversible to prevent accidental data loss."
    )
