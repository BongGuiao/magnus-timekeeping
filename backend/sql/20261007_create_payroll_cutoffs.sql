BEGIN;

CREATE SCHEMA IF NOT EXISTS payroll;

CREATE TABLE IF NOT EXISTS payroll.cutoffs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    cutoff_code varchar(50) NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    pay_date date NOT NULL,
    employee_review_deadline timestamptz,
    supervisor_deadline timestamptz,
    hr_deadline timestamptz,
    status varchar(30) NOT NULL DEFAULT 'SCHEDULED',
    locked_at timestamptz,
    locked_by uuid REFERENCES identity.users(id),
    calculation_version varchar(50),
    export_batch_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid,
    row_version integer NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT uq_cutoffs_payroll_group_code UNIQUE (payroll_group_id, cutoff_code),
    CONSTRAINT ck_cutoffs_period_dates CHECK (period_end >= period_start)
);

COMMIT;
