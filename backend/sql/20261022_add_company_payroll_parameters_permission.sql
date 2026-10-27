BEGIN;

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES (
    'payroll.company_parameters.manage',
    'payroll',
    'company_parameters_manage',
    'Manage company payroll parameters',
    'Manage company-scoped payroll calculation and statutory deduction settings.'
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
WHERE upper(role_row.role_code) IN (
    'HR_ADMIN'
)
  AND permission_row.permission_code = 'payroll.company_parameters.manage'
  AND permission_row.is_active
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
