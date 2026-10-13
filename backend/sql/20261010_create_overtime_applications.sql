BEGIN;

CREATE TABLE IF NOT EXISTS attendance.overtime_applications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_no varchar(50) NOT NULL UNIQUE,
    employee_id uuid NOT NULL REFERENCES hr.employees(id) ON DELETE CASCADE,
    attendance_record_id uuid NOT NULL
        REFERENCES attendance.attendance_records(id) ON DELETE CASCADE,
    daily_result_id uuid,
    authorization_id uuid,
    attendance_date date NOT NULL,
    requested_start_at timestamptz NOT NULL,
    requested_end_at timestamptz NOT NULL,
    potential_ot_minutes core.positive_minutes NOT NULL,
    requested_minutes core.positive_minutes NOT NULL,
    system_validated_minutes core.positive_minutes,
    supervisor_approved_minutes core.positive_minutes,
    final_payable_minutes core.positive_minutes,
    overtime_type varchar(30) NOT NULL,
    reason text NOT NULL,
    work_accomplished text,
    validation_status varchar(30),
    workflow_instance_id uuid,
    status varchar(30) NOT NULL DEFAULT 'DRAFT',
    payroll_posted boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid,
    row_version integer NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT ck_overtime_applications_requested_period
        CHECK (requested_end_at > requested_start_at),
    CONSTRAINT ck_overtime_applications_final_not_above_approved
        CHECK (
            final_payable_minutes IS NULL
            OR supervisor_approved_minutes IS NULL
            OR final_payable_minutes <= supervisor_approved_minutes
        )
);

CREATE INDEX IF NOT EXISTS ix_overtime_applications_employee
    ON attendance.overtime_applications (employee_id, attendance_date DESC);

CREATE INDEX IF NOT EXISTS ix_overtime_applications_attendance_record
    ON attendance.overtime_applications (attendance_record_id, overtime_type, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_overtime_applications_pending
    ON attendance.overtime_applications (status, created_at)
    WHERE is_active = true;

COMMIT;
