BEGIN;

ALTER TABLE payroll.cutoffs
    ADD COLUMN IF NOT EXISTS attendance_finalized_at timestamptz,
    ADD COLUMN IF NOT EXISTS attendance_finalized_by uuid
        REFERENCES identity.users(id);

UPDATE payroll.cutoffs
SET
    attendance_finalized_at = COALESCE(locked_at, attendance_deadline),
    attendance_finalized_by = locked_by
WHERE attendance_finalized_at IS NULL
  AND (
      locked_at IS NOT NULL
      OR (
          attendance_deadline IS NOT NULL
          AND attendance_deadline < now()
      )
  );

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES (
    'attendance.finalize',
    'attendance',
    'finalize',
    'Finalize attendance cutoff',
    'Finalize reviewed attendance for a payroll cutoff before payroll calculation.'
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
WHERE upper(role_row.role_code) = 'HR_ADMIN'
  AND permission_row.permission_code = 'attendance.finalize'
  AND permission_row.is_active
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
