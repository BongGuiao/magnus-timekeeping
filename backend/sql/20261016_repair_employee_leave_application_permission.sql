BEGIN;

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES (
    'leave.submit',
    'leave',
    'submit',
    'Submit leave',
    'Submit leave requests for the signed-in employee.'
)
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
JOIN identity.permissions AS permission_row
  ON permission_row.permission_code = 'leave.submit'
WHERE upper(role_row.role_code) = 'EMPLOYEE'
  AND permission_row.is_active
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
