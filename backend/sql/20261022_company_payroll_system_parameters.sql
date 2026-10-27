BEGIN;

CREATE TABLE IF NOT EXISTS payroll.company_system_parameters (
    company_id uuid PRIMARY KEY REFERENCES core.companies(id) ON DELETE CASCADE,
    year_end_wtax_reconciliation_enabled boolean NOT NULL DEFAULT false,
    thirteenth_month_enabled boolean NOT NULL DEFAULT false,
    statutory_contribution_timing varchar(20) NOT NULL DEFAULT 'PER_CUTOFF',
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES identity.users(id),
    CONSTRAINT ck_payroll_company_system_parameters_contribution_timing
        CHECK (statutory_contribution_timing IN ('PER_CUTOFF', 'FINAL_CUTOFF'))
);

INSERT INTO payroll.company_system_parameters (
    company_id,
    year_end_wtax_reconciliation_enabled,
    thirteenth_month_enabled
)
SELECT
    company.id,
    COALESCE(parameters.year_end_wtax_reconciliation_enabled, false),
    COALESCE(parameters.thirteenth_month_enabled, false)
FROM core.companies AS company
LEFT JOIN payroll.system_parameters AS parameters ON parameters.id = 1
ON CONFLICT (company_id) DO NOTHING;

ALTER TABLE payroll.thirteenth_month_runs
    ADD COLUMN IF NOT EXISTS company_id uuid REFERENCES core.companies(id);

DROP INDEX IF EXISTS payroll.uq_payroll_thirteenth_month_current_year;

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_thirteenth_month_current_year
    ON payroll.thirteenth_month_runs (company_id, tax_year)
    WHERE is_current AND company_id IS NOT NULL;

UPDATE payroll.thirteenth_month_runs
SET is_current = false
WHERE company_id IS NULL;

COMMIT;
