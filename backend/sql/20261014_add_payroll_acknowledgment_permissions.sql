BEGIN;

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES
    (
        'payroll.read_own',
        'payroll',
        'read_own',
        'View own payroll cutoff results',
        'View and acknowledge payroll cutoff calculations belonging to the signed-in employee.'
    ),
    (
        'payroll.acknowledge_team',
        'payroll',
        'acknowledge_team',
        'Acknowledge team payroll calculations',
        'View and acknowledge payroll cutoff calculations for directly assigned employees.'
    )
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN (
    VALUES
        ('EMPLOYEE', 'payroll.read_own'),
        ('SUPERVISOR', 'payroll.read_own'),
        ('MANAGER', 'payroll.read_own'),
        ('SUPERVISOR', 'payroll.acknowledge_team'),
        ('MANAGER', 'payroll.acknowledge_team')
) AS role_grant(role_code, permission_code)
JOIN identity.permissions AS permission_row
  ON permission_row.permission_code = role_grant.permission_code
WHERE upper(role_row.role_code) = role_grant.role_code
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
