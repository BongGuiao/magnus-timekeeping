BEGIN;

CREATE TABLE IF NOT EXISTS payroll.employee_loans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    reference_number varchar(50) NOT NULL UNIQUE,
    principal_amount numeric(14, 2) NOT NULL CHECK (principal_amount > 0),
    installment_amount numeric(14, 2) NOT NULL CHECK (installment_amount > 0),
    schedule varchar(20) NOT NULL CHECK (
        schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')
    ),
    effective_from date NOT NULL,
    outstanding_balance numeric(14, 2) NOT NULL CHECK (outstanding_balance >= 0),
    status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK (
        status IN ('ACTIVE', 'RETIRED', 'PAID_OFF')
    ),
    previous_loan_id uuid REFERENCES payroll.employee_loans(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id)
);

CREATE INDEX IF NOT EXISTS ix_employee_loans_group_status
    ON payroll.employee_loans (payroll_group_id, status, employee_id);

CREATE TABLE IF NOT EXISTS payroll.employee_loan_repayments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id uuid NOT NULL REFERENCES payroll.employee_loans(id),
    cutoff_id uuid NOT NULL REFERENCES payroll.cutoffs(id),
    gross_pay_run_id uuid NOT NULL REFERENCES payroll.gross_pay_runs(id),
    amount numeric(14, 2) NOT NULL CHECK (amount > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_employee_loan_repayment_cutoff UNIQUE (loan_id, cutoff_id)
);

COMMIT;
