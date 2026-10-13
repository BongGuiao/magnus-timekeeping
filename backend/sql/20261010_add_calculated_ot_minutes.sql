BEGIN;

ALTER TABLE attendance.attendance_records
    ADD COLUMN IF NOT EXISTS calculated_ot_minutes integer NOT NULL DEFAULT 0;

ALTER TABLE attendance.attendance_records
    ADD COLUMN IF NOT EXISTS overtime_hours numeric(10, 4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS regular_overtime_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS regular_overtime_hours numeric(10, 4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS night_differential_overtime_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS night_differential_overtime_hours numeric(10, 4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS night_differential_minutes integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS night_differential_hours numeric(10, 4) NOT NULL DEFAULT 0;

COMMIT;
