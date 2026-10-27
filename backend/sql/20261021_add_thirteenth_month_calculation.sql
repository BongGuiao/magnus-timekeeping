BEGIN;

ALTER TABLE payroll.system_parameters
    ADD COLUMN IF NOT EXISTS thirteenth_month_enabled boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS payroll.thirteenth_month_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year integer NOT NULL CHECK (tax_year BETWEEN 1900 AND 9999),
    calculated_at timestamptz NOT NULL,
    calculated_by uuid NOT NULL REFERENCES identity.users(id),
    is_current boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_thirteenth_month_current_year
    ON payroll.thirteenth_month_runs (tax_year)
    WHERE is_current;

CREATE TABLE IF NOT EXISTS payroll.thirteenth_month_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES payroll.thirteenth_month_runs(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    employee_no varchar(30) NOT NULL,
    employee_name varchar(240) NOT NULL,
    basic_salary_earned numeric(14, 2) NOT NULL,
    thirteenth_month_pay numeric(14, 2) NOT NULL,
    tax_exempt_amount numeric(14, 2) NOT NULL,
    taxable_amount numeric(14, 2) NOT NULL,
    source_payroll_periods integer NOT NULL,
    CONSTRAINT ck_payroll_thirteenth_month_result_amounts CHECK (
        basic_salary_earned >= 0
        AND thirteenth_month_pay >= 0
        AND tax_exempt_amount >= 0
        AND taxable_amount >= 0
        AND source_payroll_periods >= 0
    ),
    CONSTRAINT uq_payroll_thirteenth_month_result_employee UNIQUE (run_id, employee_id)
);

COMMIT;
