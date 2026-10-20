BEGIN;

ALTER TABLE payroll.benefit_types
    ADD COLUMN IF NOT EXISTS posting_schedule varchar(20) NOT NULL DEFAULT 'EVERY_CUTOFF';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_benefit_type_posting_schedule'
          AND conrelid = 'payroll.benefit_types'::regclass
    ) THEN
        ALTER TABLE payroll.benefit_types
            ADD CONSTRAINT ck_payroll_benefit_type_posting_schedule
            CHECK (posting_schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS payroll.employee_benefit_entitlements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    benefit_type_id uuid NOT NULL REFERENCES payroll.benefit_types(id),
    amount_per_occurrence numeric(14, 2) NOT NULL CHECK (amount_per_occurrence > 0),
    effective_from date NOT NULL,
    effective_to date,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_employee_benefit_entitlement_effective_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT uq_employee_benefit_entitlement_employee_type
        UNIQUE (employee_id, benefit_type_id)
);

CREATE INDEX IF NOT EXISTS ix_employee_benefit_entitlements_active_period
    ON payroll.employee_benefit_entitlements (employee_id, effective_from, effective_to)
    WHERE is_active;

COMMIT;
