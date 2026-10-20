BEGIN;

ALTER TABLE payroll.gross_pay_results
    ADD COLUMN IF NOT EXISTS gross_status varchar(20),
    ADD COLUMN IF NOT EXISTS cash_benefit_amount numeric(14, 2),
    ADD COLUMN IF NOT EXISTS non_cash_benefit_amount numeric(14, 2),
    ADD COLUMN IF NOT EXISTS employee_benefit_deductions numeric(14, 2),
    ADD COLUMN IF NOT EXISTS exempt_limited_benefit_amount numeric(14, 2),
    ADD COLUMN IF NOT EXISTS taxable_income numeric(14, 2),
    ADD COLUMN IF NOT EXISTS employee_contributions numeric(14, 2),
    ADD COLUMN IF NOT EXISTS employer_contributions numeric(14, 2),
    ADD COLUMN IF NOT EXISTS withholding_tax numeric(14, 2),
    ADD COLUMN IF NOT EXISTS net_amount numeric(14, 2),
    ADD COLUMN IF NOT EXISTS benefit_lines jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS contribution_lines jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS payroll.opening_ytd_balances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    tax_year integer NOT NULL CHECK (tax_year BETWEEN 1900 AND 9999),
    taxable_income numeric(14, 2) NOT NULL CHECK (taxable_income >= 0),
    tax_withheld numeric(14, 2) NOT NULL CHECK (tax_withheld >= 0),
    exempt_limited_benefits numeric(14, 2) NOT NULL CHECK (exempt_limited_benefits >= 0),
    previous_balance_id uuid UNIQUE
        REFERENCES payroll.opening_ytd_balances(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id)
);

CREATE INDEX IF NOT EXISTS ix_payroll_ytd_balance_employee_year_created
    ON payroll.opening_ytd_balances (employee_id, tax_year, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_ytd_balance_root
    ON payroll.opening_ytd_balances (employee_id, tax_year)
    WHERE previous_balance_id IS NULL;

CREATE OR REPLACE FUNCTION payroll.reject_opening_ytd_balance_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Opening YTD balance records are immutable; append a replacement record.';
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_payroll_opening_ytd_balances_immutable
    ON payroll.opening_ytd_balances;
CREATE TRIGGER trg_payroll_opening_ytd_balances_immutable
    BEFORE UPDATE OR DELETE ON payroll.opening_ytd_balances
    FOR EACH ROW EXECUTE FUNCTION payroll.reject_opening_ytd_balance_mutation();

COMMIT;
