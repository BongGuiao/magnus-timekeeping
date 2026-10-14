BEGIN;

ALTER TABLE payroll.employee_cutoff_results
    ADD COLUMN IF NOT EXISTS official_business_minutes core.positive_minutes NOT NULL DEFAULT 0;

COMMIT;
