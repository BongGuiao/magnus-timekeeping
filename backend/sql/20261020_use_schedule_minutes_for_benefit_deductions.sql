BEGIN;

ALTER TABLE payroll.benefit_types
    ADD COLUMN IF NOT EXISTS attendance_based boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deduct_for_late boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deduct_for_undertime boolean NOT NULL DEFAULT false;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'payroll'
          AND table_name = 'benefit_types'
          AND column_name = 'late_deduction_per_minute'
    ) THEN
        EXECUTE '
            UPDATE payroll.benefit_types
            SET deduct_for_late = late_deduction_per_minute > 0
        ';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'payroll'
          AND table_name = 'benefit_types'
          AND column_name = 'undertime_deduction_per_minute'
    ) THEN
        EXECUTE '
            UPDATE payroll.benefit_types
            SET deduct_for_undertime = undertime_deduction_per_minute > 0
        ';
    END IF;
END $$;

ALTER TABLE payroll.benefit_types
    DROP CONSTRAINT IF EXISTS ck_payroll_benefit_attendance_deduction_rates,
    DROP CONSTRAINT IF EXISTS ck_payroll_benefit_deduction_rates_require_attendance,
    DROP CONSTRAINT IF EXISTS ck_payroll_benefit_time_deductions_require_attendance,
    ADD CONSTRAINT ck_payroll_benefit_time_deductions_require_attendance
        CHECK (
            attendance_based
            OR (deduct_for_late = false AND deduct_for_undertime = false)
        ),
    DROP COLUMN IF EXISTS late_deduction_per_minute,
    DROP COLUMN IF EXISTS undertime_deduction_per_minute;

ALTER TABLE payroll.cutoff_benefits
    ADD COLUMN IF NOT EXISTS attendance_based boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deduct_for_late boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deduct_for_undertime boolean NOT NULL DEFAULT false;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'payroll'
          AND table_name = 'cutoff_benefits'
          AND column_name = 'late_deduction_per_minute'
    ) THEN
        EXECUTE '
            UPDATE payroll.cutoff_benefits
            SET deduct_for_late = late_deduction_per_minute > 0
        ';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'payroll'
          AND table_name = 'cutoff_benefits'
          AND column_name = 'undertime_deduction_per_minute'
    ) THEN
        EXECUTE '
            UPDATE payroll.cutoff_benefits
            SET deduct_for_undertime = undertime_deduction_per_minute > 0
        ';
    END IF;
END $$;

ALTER TABLE payroll.cutoff_benefits
    DROP CONSTRAINT IF EXISTS ck_payroll_cutoff_benefit_attendance_deduction_rates,
    DROP CONSTRAINT IF EXISTS ck_payroll_cutoff_benefit_deduction_rates_require_attendance,
    DROP CONSTRAINT IF EXISTS ck_payroll_cutoff_benefit_time_deductions_require_attendance,
    ADD CONSTRAINT ck_payroll_cutoff_benefit_time_deductions_require_attendance
        CHECK (
            attendance_based
            OR (deduct_for_late = false AND deduct_for_undertime = false)
        ),
    DROP COLUMN IF EXISTS late_deduction_per_minute,
    DROP COLUMN IF EXISTS undertime_deduction_per_minute;

ALTER TABLE payroll.employee_cutoff_results
    ADD COLUMN IF NOT EXISTS required_work_minutes core.positive_minutes NOT NULL DEFAULT 0;

COMMIT;
