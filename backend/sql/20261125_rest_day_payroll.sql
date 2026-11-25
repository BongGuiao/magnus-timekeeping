-- Mirrors Alembic revision f5b7d9e1a3c5. Configure combined rates separately.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_rest_day_open_application
    ON attendance.overtime_applications (employee_id, attendance_date)
    WHERE is_active AND overtime_type = 'REST_DAY_WORK'
      AND status IN ('PENDING', 'APPROVED');

ALTER TABLE payroll.employee_cutoff_results
    ADD COLUMN IF NOT EXISTS holiday_rest_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS holiday_rest_ot_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS double_holiday_rest_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS double_holiday_rest_ot_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS special_rest_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS special_rest_ot_minutes core.positive_minutes NOT NULL DEFAULT 0;

ALTER TABLE payroll.earning_rules
    DROP CONSTRAINT IF EXISTS ck_payroll_earning_rules_component,
    ADD CONSTRAINT ck_payroll_earning_rules_component CHECK (
        component_code IN (
            'REGULAR', 'PAID_LEAVE', 'OFFICIAL_BUSINESS', 'REST_DAY', 'SPECIAL_DAY',
            'HOLIDAY', 'ORDINARY_OT', 'REST_DAY_OT', 'SPECIAL_DAY_OT', 'HOLIDAY_OT',
            'NIGHT_REGULAR', 'NIGHT_OT', 'UNWORKED_HOLIDAY', 'UNWORKED_DOUBLE_HOLIDAY',
            'HOLIDAY_REST', 'HOLIDAY_REST_OT', 'DOUBLE_HOLIDAY_REST',
            'DOUBLE_HOLIDAY_REST_OT', 'SPECIAL_REST', 'SPECIAL_REST_OT'
        )
    );

COMMIT;
