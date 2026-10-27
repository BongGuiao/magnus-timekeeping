BEGIN;

CREATE TABLE IF NOT EXISTS payroll.off_cycle_payroll_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES core.companies(id),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    benefit_type_id uuid NOT NULL REFERENCES payroll.benefit_types(id),
    thirteenth_month_run_id uuid REFERENCES payroll.thirteenth_month_runs(id),
    run_type varchar(30) NOT NULL DEFAULT 'BENEFIT',
    proposed_payment_date date NOT NULL,
    actual_payment_date date,
    status varchar(20) NOT NULL DEFAULT 'DRAFT',
    notes text,
    rejection_reason text,
    created_by uuid NOT NULL REFERENCES identity.users(id),
    submitted_at timestamptz,
    approved_by uuid REFERENCES identity.users(id),
    approved_at timestamptz,
    paid_by uuid REFERENCES identity.users(id),
    paid_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_off_cycle_payroll_run_status
        CHECK (status IN ('DRAFT', 'PENDING', 'APPROVED', 'PAID', 'REJECTED')),
    CONSTRAINT ck_off_cycle_payroll_run_source
        CHECK (
            (run_type = 'BENEFIT' AND benefit_type_id IS NOT NULL
                AND thirteenth_month_run_id IS NULL)
            OR
            (run_type = 'THIRTEENTH_MONTH' AND benefit_type_id IS NOT NULL
                AND thirteenth_month_run_id IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS ix_off_cycle_payroll_run_paid_company_date
    ON payroll.off_cycle_payroll_runs (company_id, actual_payment_date)
    WHERE status = 'PAID';

CREATE TABLE IF NOT EXISTS payroll.off_cycle_payroll_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES payroll.off_cycle_payroll_runs(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    thirteenth_month_result_id uuid REFERENCES payroll.thirteenth_month_results(id),
    employee_no varchar(30) NOT NULL,
    benefit_code varchar(30) NOT NULL,
    benefit_name varchar(120) NOT NULL,
    category varchar(30) NOT NULL,
    tax_treatment varchar(20) NOT NULL,
    withholding_timing varchar(20) NOT NULL DEFAULT 'PAY_PERIOD',
    amount numeric(14, 2) NOT NULL,
    taxable_amount numeric(14, 2) NOT NULL DEFAULT 0,
    exempt_limited_amount numeric(14, 2) NOT NULL DEFAULT 0,
    withholding_tax numeric(14, 2) NOT NULL DEFAULT 0,
    net_amount numeric(14, 2) NOT NULL DEFAULT 0,
    notes text,
    CONSTRAINT ck_off_cycle_payroll_line_amount CHECK (amount > 0),
    CONSTRAINT ck_off_cycle_payroll_line_tax_amounts
        CHECK (
            taxable_amount >= 0 AND exempt_limited_amount >= 0
            AND withholding_tax >= 0 AND net_amount >= 0
        ),
    CONSTRAINT uq_off_cycle_payroll_line_run_employee UNIQUE (run_id, employee_id)
);

-- A 13th-month result may be reissued only after its earlier run is rejected;
-- the repository enforces this across runs.
CREATE INDEX IF NOT EXISTS ix_off_cycle_payroll_line_13m_result
    ON payroll.off_cycle_payroll_lines (thirteenth_month_result_id);
CREATE INDEX IF NOT EXISTS ix_off_cycle_payroll_line_employee
    ON payroll.off_cycle_payroll_lines (employee_id);

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN identity.permissions AS permission_row
WHERE upper(role_row.role_code) = 'PAYROLL_HEAD'
  AND permission_row.permission_code = 'payroll.approve'
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

COMMIT;
