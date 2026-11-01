-- Missing-punch filing and supervisor approval. No attendance punches are backfilled.
BEGIN;

CREATE TABLE IF NOT EXISTS attendance.correction_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    user_id uuid NOT NULL REFERENCES identity.users(id),
    attendance_record_id uuid REFERENCES attendance.attendance_records(id),
    work_date date NOT NULL,
    original_clock_in_at timestamptz,
    original_clock_out_at timestamptz,
    requested_clock_in_at timestamptz NOT NULL,
    requested_clock_out_at timestamptz NOT NULL,
    reason text NOT NULL,
    supporting_reference varchar(500),
    status varchar(20) NOT NULL DEFAULT 'PENDING',
    created_at timestamptz NOT NULL DEFAULT now(),
    reviewed_by uuid REFERENCES identity.users(id),
    reviewed_at timestamptz,
    review_notes text,
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_corrections_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT ck_corrections_period CHECK (requested_clock_out_at > requested_clock_in_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_corrections_pending_employee_date
    ON attendance.correction_requests(employee_id, work_date) WHERE status = 'PENDING';

INSERT INTO identity.permissions(permission_code, module_code, action_code, permission_name, description)
VALUES
    ('attendance.correct_own', 'attendance', 'correct_own', 'File own missing-punch corrections',
     'File and view missing-punch correction requests for the signed-in employee.'),
    ('attendance.approve_corrections_team', 'attendance', 'approve_corrections_team',
     'Approve team missing-punch corrections', 'Approve or reject missing-punch requests of current direct reports.')
ON CONFLICT (permission_code) DO UPDATE SET
    module_code = EXCLUDED.module_code, action_code = EXCLUDED.action_code,
    permission_name = EXCLUDED.permission_name, description = EXCLUDED.description, is_active = true;

INSERT INTO identity.role_permissions(role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles role_row CROSS JOIN identity.permissions permission_row
WHERE
    (permission_row.permission_code = 'attendance.correct_own'
     AND upper(role_row.role_code) IN ('EMPLOYEE', 'SUPERVISOR'))
    OR (permission_row.permission_code = 'attendance.approve_corrections_team'
        AND upper(role_row.role_code) = 'SUPERVISOR')
ON CONFLICT (role_id, permission_id) DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
