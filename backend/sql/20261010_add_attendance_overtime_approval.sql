BEGIN;

ALTER TABLE attendance.attendance_records
    ADD COLUMN IF NOT EXISTS overtime_request_status varchar(20),
    ADD COLUMN IF NOT EXISTS requested_regular_overtime_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS requested_night_differential_overtime_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS requested_night_differential_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS overtime_requested_at timestamptz,
    ADD COLUMN IF NOT EXISTS approved_regular_overtime_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS approved_night_differential_overtime_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS approved_night_differential_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS overtime_approved_by_id uuid REFERENCES identity.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS overtime_approved_at timestamptz;

CREATE INDEX IF NOT EXISTS ix_attendance_records_overtime_request_status
    ON attendance.attendance_records (overtime_request_status, work_date);

COMMIT;
