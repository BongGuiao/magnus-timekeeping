-- Management directive: payroll is restricted to HR personnel only.
-- System administrators (IT operations) must not hold any payroll permission.
-- Also adds team-scoped employee reads so supervisors see only direct reports.
BEGIN;

DELETE FROM identity.role_permissions AS role_permission
USING identity.roles AS role_row, identity.permissions AS permission_row
WHERE role_permission.role_id = role_row.id
  AND role_permission.permission_id = permission_row.id
  AND upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR')
  AND permission_row.permission_code LIKE 'payroll.%';

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN identity.permissions AS permission_row
WHERE upper(role_row.role_code) = 'HR_ADMIN'
  AND permission_row.permission_code IN (
      'payroll.manage',
      'payroll.approve',
      'payroll.company_parameters.manage'
  )
  AND permission_row.is_active
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES (
    'employees.read_team',
    'employees',
    'read_team',
    'View team employees',
    'View employee records of current direct reports only.'
)
ON CONFLICT (permission_code) DO UPDATE
SET
    module_code = EXCLUDED.module_code,
    action_code = EXCLUDED.action_code,
    permission_name = EXCLUDED.permission_name,
    description = EXCLUDED.description,
    is_active = true;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN identity.permissions AS permission_row
WHERE upper(role_row.role_code) = 'SUPERVISOR'
  AND permission_row.permission_code = 'employees.read_team'
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

-- Supervisors must only see their direct reports, never the organisation-wide list.
DELETE FROM identity.role_permissions AS role_permission
USING identity.roles AS role_row, identity.permissions AS permission_row
WHERE role_permission.role_id = role_row.id
  AND role_permission.permission_id = permission_row.id
  AND upper(role_row.role_code) = 'SUPERVISOR'
  AND permission_row.permission_code = 'employees.read';

COMMIT;

-- Verification: must return zero rows.
SELECT role_row.role_code, permission_row.permission_code
FROM identity.role_permissions AS role_permission
JOIN identity.roles AS role_row ON role_row.id = role_permission.role_id
JOIN identity.permissions AS permission_row ON permission_row.id = role_permission.permission_id
WHERE upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR')
  AND role_permission.allowed
  AND permission_row.permission_code LIKE 'payroll.%';
