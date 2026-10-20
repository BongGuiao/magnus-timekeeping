BEGIN;

ALTER TABLE payroll.benefit_types
    ADD COLUMN IF NOT EXISTS attendance_based boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS late_deduction_per_minute numeric(14, 4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS undertime_deduction_per_minute numeric(14, 4) NOT NULL DEFAULT 0;

ALTER TABLE payroll.cutoff_benefits
    ADD COLUMN IF NOT EXISTS attendance_based boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS late_deduction_per_minute numeric(14, 4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS undertime_deduction_per_minute numeric(14, 4) NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_benefit_deduction_not_attendance_based'
    ) THEN
        ALTER TABLE payroll.benefit_types
            ADD CONSTRAINT ck_payroll_benefit_deduction_not_attendance_based
            CHECK (category != 'EMPLOYEE_DEDUCTION' OR attendance_based = false);
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_benefit_attendance_deduction_rates'
    ) THEN
        ALTER TABLE payroll.benefit_types
            ADD CONSTRAINT ck_payroll_benefit_attendance_deduction_rates
            CHECK (
                late_deduction_per_minute >= 0
                AND undertime_deduction_per_minute >= 0
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_benefit_deduction_rates_require_attendance'
    ) THEN
        ALTER TABLE payroll.benefit_types
            ADD CONSTRAINT ck_payroll_benefit_deduction_rates_require_attendance
            CHECK (
                attendance_based
                OR (late_deduction_per_minute = 0 AND undertime_deduction_per_minute = 0)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_cutoff_benefit_deduction_not_attendance_based'
    ) THEN
        ALTER TABLE payroll.cutoff_benefits
            ADD CONSTRAINT ck_payroll_cutoff_benefit_deduction_not_attendance_based
            CHECK (category != 'EMPLOYEE_DEDUCTION' OR attendance_based = false);
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_cutoff_benefit_attendance_deduction_rates'
    ) THEN
        ALTER TABLE payroll.cutoff_benefits
            ADD CONSTRAINT ck_payroll_cutoff_benefit_attendance_deduction_rates
            CHECK (
                late_deduction_per_minute >= 0
                AND undertime_deduction_per_minute >= 0
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_cutoff_benefit_deduction_rates_require_attendance'
    ) THEN
        ALTER TABLE payroll.cutoff_benefits
            ADD CONSTRAINT ck_payroll_cutoff_benefit_deduction_rates_require_attendance
            CHECK (
                attendance_based
                OR (late_deduction_per_minute = 0 AND undertime_deduction_per_minute = 0)
            );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS payroll.employee_benefit_deductions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    benefit_type_id uuid NOT NULL REFERENCES payroll.benefit_types(id),
    amount_per_occurrence numeric(14, 2) NOT NULL CHECK (amount_per_occurrence > 0),
    schedule varchar(20) NOT NULL CHECK (
        schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')
    ),
    effective_from date NOT NULL,
    effective_to date,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_employee_benefit_deduction_effective_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT uq_employee_benefit_deduction_employee_type
        UNIQUE (employee_id, benefit_type_id)
);

CREATE INDEX IF NOT EXISTS ix_employee_benefit_deductions_active_period
    ON payroll.employee_benefit_deductions (employee_id, effective_from, effective_to)
    WHERE is_active;

COMMIT;
