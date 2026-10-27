BEGIN;

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES (
    'payroll.approve',
    'payroll',
    'approve',
    'Approve and finalize payroll',
    'Approve calculated payroll cutoffs after all employee results are ready.'
)
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN identity.permissions AS permission_row
WHERE upper(role_row.role_code) IN (
    'HR_ADMIN'
)
  AND permission_row.permission_code = 'payroll.approve'
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
