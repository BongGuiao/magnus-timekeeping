INSERT INTO identity.permissions
    (permission_code, module_code, action_code, permission_name, description)
VALUES (
    'schedule.manage_team', 'schedule', 'manage_team',
    'Manage team schedule assignments',
    'Manage schedule assignments for current direct reports.'
)
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT r.id, p.id, true
FROM identity.roles r CROSS JOIN identity.permissions p
WHERE upper(r.role_code) = 'SUPERVISOR'
  AND p.permission_code = 'schedule.manage_team'
ON CONFLICT (role_id, permission_id) DO NOTHING;
