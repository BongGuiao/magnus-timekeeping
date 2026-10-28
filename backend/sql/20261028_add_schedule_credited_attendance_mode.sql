BEGIN;

ALTER TABLE schedule.employee_schedule_assignments
    ADD COLUMN IF NOT EXISTS attendance_mode varchar(30) NOT NULL DEFAULT 'PUNCH_REQUIRED';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_employee_schedule_assignments_attendance_mode'
          AND conrelid = 'schedule.employee_schedule_assignments'::regclass
    ) THEN
        ALTER TABLE schedule.employee_schedule_assignments
            ADD CONSTRAINT ck_employee_schedule_assignments_attendance_mode
            CHECK (attendance_mode IN ('PUNCH_REQUIRED', 'SCHEDULE_CREDITED'));
    END IF;
END $$;

COMMIT;
