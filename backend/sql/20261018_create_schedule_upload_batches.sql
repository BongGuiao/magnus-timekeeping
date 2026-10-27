BEGIN;

CREATE SEQUENCE IF NOT EXISTS schedule.schedule_upload_batch_no_seq;

CREATE TABLE IF NOT EXISTS schedule.schedule_upload_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_no varchar(30) NOT NULL,
    supervisor_employee_id uuid NOT NULL REFERENCES hr.employees(id),
    uploaded_by uuid NOT NULL REFERENCES identity.users(id),
    file_name varchar(255) NOT NULL,
    row_count integer NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'PENDING_APPROVAL',
    submitted_at timestamptz NOT NULL DEFAULT now(),
    reviewed_by uuid REFERENCES identity.users(id),
    reviewed_at timestamptz,
    review_remarks text,
    CONSTRAINT uq_schedule_upload_batches_batch_no UNIQUE (batch_no),
    CONSTRAINT ck_schedule_upload_batches_row_count CHECK (row_count > 0),
    CONSTRAINT ck_schedule_upload_batches_status CHECK (
        status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CANCELLED')
    ),
    CONSTRAINT ck_schedule_upload_batches_review CHECK (
        (status = 'PENDING_APPROVAL') = (reviewed_by IS NULL AND reviewed_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_schedule_upload_batches_status_submitted
    ON schedule.schedule_upload_batches (status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS ix_schedule_upload_batches_uploaded_by_submitted
    ON schedule.schedule_upload_batches (uploaded_by, submitted_at DESC);

CREATE TABLE IF NOT EXISTS schedule.schedule_upload_batch_rows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id uuid NOT NULL
        REFERENCES schedule.schedule_upload_batches(id) ON DELETE CASCADE,
    row_no integer NOT NULL,
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    employee_code varchar(30) NOT NULL,
    employee_name varchar(255) NOT NULL,
    schedule_code varchar(30) NOT NULL,
    assignment_type varchar(30) NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    rest_day_pattern_code varchar(30),
    reason text,
    employee_schedule_assignment_id uuid
        REFERENCES schedule.employee_schedule_assignments(id),
    CONSTRAINT uq_schedule_upload_batch_rows_batch_row UNIQUE (batch_id, row_no),
    CONSTRAINT ck_schedule_upload_batch_rows_row_no CHECK (row_no > 0),
    CONSTRAINT ck_schedule_upload_batch_rows_effective_dates CHECK (
        effective_to IS NULL OR effective_to >= effective_from
    )
);

CREATE INDEX IF NOT EXISTS ix_schedule_upload_batch_rows_employee
    ON schedule.schedule_upload_batch_rows (employee_id);

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES
    (
        'schedule.upload_team',
        'schedule',
        'upload_team',
        'Upload team schedules',
        'Upload CSV schedule assignments for directly assigned employees, subject to approval.'
    ),
    (
        'schedule.approve',
        'schedule',
        'approve',
        'Approve uploaded schedules',
        'Review, approve, or reject schedule upload batches submitted by supervisors.'
    ),
    (
        'schedule.read_own',
        'schedule',
        'read_own',
        'View own schedule',
        'View current and upcoming approved schedule assignments of the signed-in employee.'
    )
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN (
    VALUES
        ('SUPERVISOR', 'schedule.upload_team'),
        ('MANAGER', 'schedule.upload_team'),
        ('HR_ADMIN', 'schedule.approve'),
        ('SYSTEM_ADMIN', 'schedule.approve'),
        ('SYSTEM_ADMINISTRATOR', 'schedule.approve'),
        ('EMPLOYEE', 'schedule.read_own'),
        ('SUPERVISOR', 'schedule.read_own'),
        ('MANAGER', 'schedule.read_own'),
        ('HR_ADMIN', 'schedule.read_own')
) AS role_grant(role_code, permission_code)
JOIN identity.permissions AS permission_row
  ON permission_row.permission_code = role_grant.permission_code
WHERE upper(role_row.role_code) = role_grant.role_code
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
