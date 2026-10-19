BEGIN;

CREATE TABLE IF NOT EXISTS schedule.emergency_schedule_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id) ON DELETE CASCADE,
    requested_by uuid NOT NULL REFERENCES identity.users(id),
    schedule_template_id uuid NOT NULL REFERENCES schedule.schedule_templates(id),
    work_date date NOT NULL,
    reason text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'PENDING_APPROVAL',
    requested_at timestamptz NOT NULL DEFAULT now(),
    reviewed_by uuid REFERENCES identity.users(id),
    reviewed_at timestamptz,
    review_remarks text,
    CONSTRAINT ck_emergency_schedule_requests_status CHECK (
        status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')
    ),
    CONSTRAINT ck_emergency_schedule_requests_review CHECK (
        (status = 'PENDING_APPROVAL') = (reviewed_by IS NULL AND reviewed_at IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_emergency_schedule_requests_active_day
    ON schedule.emergency_schedule_requests (employee_id, work_date)
    WHERE status IN ('PENDING_APPROVAL', 'APPROVED');

CREATE INDEX IF NOT EXISTS ix_emergency_schedule_requests_pending_date
    ON schedule.emergency_schedule_requests (status, work_date);

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES
    (
        'schedule.request_emergency',
        'schedule',
        'request_emergency',
        'Request emergency schedule change',
        'Request a one-day emergency schedule replacement for supervisor approval.'
    ),
    (
        'schedule.approve_emergency',
        'schedule',
        'approve_emergency',
        'Approve emergency schedule changes',
        'Review one-day emergency schedule replacements for directly assigned employees.'
    )
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN (
    VALUES
        ('EMPLOYEE', 'schedule.request_emergency'),
        ('SUPERVISOR', 'schedule.request_emergency'),
        ('MANAGER', 'schedule.request_emergency'),
        ('HR_ADMIN', 'schedule.request_emergency'),
        ('SUPERVISOR', 'schedule.approve_emergency'),
        ('MANAGER', 'schedule.approve_emergency')
) AS role_grant(role_code, permission_code)
JOIN identity.permissions AS permission_row
  ON permission_row.permission_code = role_grant.permission_code
WHERE upper(role_row.role_code) = role_grant.role_code
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
