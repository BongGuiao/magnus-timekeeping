CREATE SCHEMA IF NOT EXISTS identity;

CREATE TABLE IF NOT EXISTS identity.permissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    permission_code varchar(100) NOT NULL UNIQUE,
    module_code varchar(50) NOT NULL DEFAULT 'general',
    action_code varchar(50),
    permission_name varchar(150) NOT NULL,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE identity.permissions
    ADD COLUMN IF NOT EXISTS module_code varchar(50) NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS action_code varchar(50),
    ADD COLUMN IF NOT EXISTS permission_name varchar(150),
    ADD COLUMN IF NOT EXISTS description text,
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'identity'
          AND table_name = 'permissions'
          AND column_name = 'name'
    ) THEN
        EXECUTE '
            UPDATE identity.permissions
            SET permission_name = name
            WHERE permission_name IS NULL
        ';
    END IF;
END;
$$;

UPDATE identity.permissions
SET permission_name = permission_code
WHERE permission_name IS NULL;

UPDATE identity.permissions
SET module_code = split_part(permission_code, '.', 1)
WHERE module_code IS NULL OR module_code = 'general';

UPDATE identity.permissions
SET action_code = NULLIF(split_part(permission_code, '.', 2), '')
WHERE action_code IS NULL;

ALTER TABLE identity.permissions
    ALTER COLUMN permission_name SET NOT NULL,
    ALTER COLUMN module_code SET NOT NULL,
    ALTER COLUMN module_code SET DEFAULT 'general';

CREATE TABLE IF NOT EXISTS identity.role_permissions (
    role_id uuid NOT NULL REFERENCES identity.roles(id) ON DELETE CASCADE,
    permission_id uuid NOT NULL REFERENCES identity.permissions(id) ON DELETE CASCADE,
    allowed boolean NOT NULL DEFAULT true,
    PRIMARY KEY (role_id, permission_id)
);

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES
    ('attendance.read_own', 'attendance', 'read_own', 'View own attendance', 'View attendance records belonging to the signed-in employee.'),
    ('attendance.read_team', 'attendance', 'read_team', 'View team attendance', 'View attendance within the supervisor team scope.'),
    ('attendance.read_org', 'attendance', 'read_org', 'View organization attendance', 'View attendance within the manager organization scope.'),
    ('leave.read_own', 'leave', 'read_own', 'View own leave', 'View leave requests belonging to the signed-in employee.'),
    ('leave.submit', 'leave', 'submit', 'Submit leave', 'Submit leave requests for the signed-in employee.'),
    ('leave.approve_team', 'leave', 'approve_team', 'Approve team leave', 'Review and approve leave within the assigned team scope.'),
    ('leave.manage', 'leave', 'manage', 'Manage leave administration', 'Manage leave types, balances, and HR leave records.'),
    ('overtime.submit_own', 'overtime', 'submit_own', 'Submit own overtime', 'Submit overtime requests for the signed-in employee.'),
    ('overtime.approve_team', 'overtime', 'approve_team', 'Approve team overtime', 'Review overtime within the assigned team scope.'),
    ('official_business.submit_own', 'official_business', 'submit_own', 'Submit own official business', 'Submit official-business requests for the signed-in employee.'),
    ('official_business.approve_team', 'official_business', 'approve_team', 'Approve team official business', 'Review requests within the assigned team scope.'),
    ('employees.read', 'employees', 'read', 'View employees', 'View employee records within the authorized organizational scope.'),
    ('employees.manage', 'employees', 'manage', 'Manage employees', 'Create and update employee records.'),
    ('company.setup', 'company', 'setup', 'Manage company setup', 'Manage company and organization configuration.'),
    ('payroll.manage', 'payroll', 'manage', 'Manage payroll setup', 'Manage payroll groups, cutoffs, and related configuration.'),
    ('schedule.manage', 'schedule', 'manage', 'Manage schedule setup', 'Manage schedule and rest-day configuration.'),
    ('roles.manage', 'roles', 'manage', 'Manage roles and permissions', 'Manage role definitions, assignments, and permission grants.'),
    ('system.manage', 'system', 'manage', 'Manage system configuration', 'Manage system-wide configuration and administration.')
ON CONFLICT (permission_code) DO NOTHING;

UPDATE identity.permissions
SET module_code = split_part(permission_code, '.', 1)
WHERE module_code IS NULL OR module_code = 'general';

UPDATE identity.permissions
SET action_code = NULLIF(split_part(permission_code, '.', 2), '')
WHERE action_code IS NULL;

WITH role_grants (role_code, permission_code) AS (
    SELECT upper(role_row.role_code), permission.permission_code
    FROM identity.roles AS role_row
    CROSS JOIN identity.permissions AS permission
    WHERE upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR')
      AND permission.is_active
      -- Payroll is restricted to HR personnel by management directive.
      AND permission.permission_code NOT LIKE 'payroll.%'
    UNION ALL
    SELECT *
    FROM (VALUES
        ('HR_ADMIN', 'attendance.read_org'),
        ('HR_ADMIN', 'leave.read_own'),
        ('HR_ADMIN', 'leave.manage'),
        ('HR_ADMIN', 'employees.read'),
        ('HR_ADMIN', 'employees.manage'),
        ('HR_ADMIN', 'company.setup'),
        ('HR_ADMIN', 'payroll.manage'),
        ('HR_ADMIN', 'schedule.manage'),
        ('MANAGER', 'attendance.read_own'),
        ('MANAGER', 'attendance.read_team'),
        ('MANAGER', 'attendance.read_org'),
        ('MANAGER', 'leave.read_own'),
        ('MANAGER', 'leave.approve_team'),
        ('MANAGER', 'overtime.approve_team'),
        ('MANAGER', 'official_business.approve_team'),
        ('MANAGER', 'employees.read'),
        ('SUPERVISOR', 'attendance.read_own'),
        ('SUPERVISOR', 'attendance.read_team'),
        ('SUPERVISOR', 'leave.read_own'),
        ('SUPERVISOR', 'leave.approve_team'),
        ('SUPERVISOR', 'overtime.approve_team'),
        ('SUPERVISOR', 'official_business.approve_team'),
        ('EMPLOYEE', 'attendance.read_own'),
        ('EMPLOYEE', 'leave.read_own'),
        ('EMPLOYEE', 'leave.submit'),
        ('EMPLOYEE', 'overtime.submit_own'),
        ('EMPLOYEE', 'official_business.submit_own')
    ) AS proposed(role_code, permission_code)
)
INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM role_grants AS role_grant
JOIN identity.roles AS role_row ON upper(role_row.role_code) = role_grant.role_code
JOIN identity.permissions AS permission_row
  ON permission_row.permission_code = role_grant.permission_code
WHERE permission_row.is_active
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

SELECT
    role_row.role_code,
    COUNT(*) FILTER (WHERE role_permission.allowed AND permission_row.is_active) AS active_permission_count,
    ARRAY_AGG(permission_row.permission_code ORDER BY permission_row.permission_code)
        FILTER (WHERE role_permission.allowed AND permission_row.is_active) AS active_permissions
FROM identity.roles AS role_row
LEFT JOIN identity.role_permissions AS role_permission
    ON role_permission.role_id = role_row.id
LEFT JOIN identity.permissions AS permission_row
    ON permission_row.id = role_permission.permission_id
WHERE upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR', 'EMPLOYEE')
GROUP BY role_row.role_code
ORDER BY role_row.role_code;
