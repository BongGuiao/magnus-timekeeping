BEGIN;

ALTER TABLE attendance.attendance_records
    ADD COLUMN IF NOT EXISTS schedule_template_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_attendance_records_schedule_template'
          AND conrelid = 'attendance.attendance_records'::regclass
    ) THEN
        ALTER TABLE attendance.attendance_records
            ADD CONSTRAINT fk_attendance_records_schedule_template
            FOREIGN KEY (schedule_template_id)
            REFERENCES schedule.schedule_templates(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

COMMIT;
