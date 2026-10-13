-- Move application logins from core.users to identity.users (+ identity.user_roles)
-- and repoint attendance foreign keys. Idempotent; core.users is kept as a backup.
BEGIN;

INSERT INTO identity.users (
    id, employee_id, username, email, password_hash, account_status,
    failed_login_count, mfa_enabled, password_changed_at,
    created_at, created_by, updated_at, updated_by, is_active
)
SELECT
    account.id,
    employee.id,
    account.employee_code,
    lower(account.email),
    account.hashed_password,
    CASE WHEN account.is_active THEN 'ACTIVE' ELSE 'DISABLED' END,
    0,
    false,
    NULL,
    account.created_at,
    account.created_by,
    account.updated_at,
    account.updated_by,
    account.is_active
FROM core.users AS account
LEFT JOIN hr.employees AS employee ON employee.employee_no = account.employee_code
ON CONFLICT DO NOTHING;

INSERT INTO identity.user_roles (user_id, role_id, effective_from, assigned_by)
SELECT
    account.id,
    role.id,
    (account.created_at AT TIME ZONE 'Asia/Manila')::date,
    NULL
FROM core.users AS account
JOIN identity.users AS migrated ON migrated.id = account.id
JOIN identity.roles AS role
  ON role.role_code = CASE WHEN upper(account.role) = 'ADMIN' THEN 'SYSTEM_ADMIN' ELSE 'EMPLOYEE' END
WHERE NOT EXISTS (
    SELECT 1 FROM identity.user_roles AS existing
    WHERE existing.user_id = account.id AND existing.role_id = role.id
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM attendance.attendance_records AS record
        LEFT JOIN identity.users AS account ON account.id = record.user_id
        WHERE account.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot repoint attendance_records.user_id: some records have no identity.users account.';
    END IF;

    ALTER TABLE attendance.attendance_records DROP CONSTRAINT IF EXISTS fk_attendance_user_id;
    ALTER TABLE attendance.attendance_records
        ADD CONSTRAINT fk_attendance_user_id
        FOREIGN KEY (user_id) REFERENCES identity.users(id) ON DELETE CASCADE;

    UPDATE attendance.attendance_records AS record
    SET approved_by_id = NULL
    WHERE approved_by_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM identity.users AS account WHERE account.id = record.approved_by_id);

    ALTER TABLE attendance.attendance_records DROP CONSTRAINT IF EXISTS fk_attendance_approved_by_id;
    ALTER TABLE attendance.attendance_records
        ADD CONSTRAINT fk_attendance_approved_by_id
        FOREIGN KEY (approved_by_id) REFERENCES identity.users(id) ON DELETE SET NULL;
END
$$;

COMMIT;
