BEGIN;

CREATE TABLE IF NOT EXISTS payroll.benefit_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    code varchar(30) NOT NULL,
    name varchar(120) NOT NULL,
    category varchar(30) NOT NULL CHECK (
        category IN (
            'CASH_ALLOWANCE', 'ONE_TIME_BONUS', 'REIMBURSEMENT',
            'EMPLOYER_PAID_INSURANCE', 'NON_CASH', 'EMPLOYEE_DEDUCTION'
        )
    ),
    tax_treatment varchar(20) NOT NULL CHECK (
        tax_treatment IN ('TAXABLE', 'EXEMPT', 'EXEMPT_LIMITED')
    ),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_payroll_benefit_deduction_tax_treatment
        CHECK (category != 'EMPLOYEE_DEDUCTION' OR tax_treatment = 'EXEMPT'),
    CONSTRAINT uq_payroll_benefit_type_group_code
        UNIQUE (payroll_group_id, code)
);

CREATE TABLE IF NOT EXISTS payroll.cutoff_benefits (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cutoff_id uuid NOT NULL REFERENCES payroll.cutoffs(id),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    benefit_type_id uuid NOT NULL REFERENCES payroll.benefit_types(id),
    benefit_code varchar(30) NOT NULL,
    benefit_name varchar(120) NOT NULL,
    category varchar(30) NOT NULL CHECK (
        category IN (
            'CASH_ALLOWANCE', 'ONE_TIME_BONUS', 'REIMBURSEMENT',
            'EMPLOYER_PAID_INSURANCE', 'NON_CASH', 'EMPLOYEE_DEDUCTION'
        )
    ),
    tax_treatment varchar(20) NOT NULL CHECK (
        tax_treatment IN ('TAXABLE', 'EXEMPT', 'EXEMPT_LIMITED')
    ),
    amount numeric(14, 2) NOT NULL CHECK (amount > 0),
    notes varchar(500),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT uq_payroll_cutoff_benefit_employee_type
        UNIQUE (cutoff_id, employee_id, benefit_type_id)
);

CREATE INDEX IF NOT EXISTS ix_payroll_cutoff_benefits_cutoff_employee
    ON payroll.cutoff_benefits (cutoff_id, employee_id);

COMMIT;
