BEGIN;

ALTER TABLE payroll.employee_cutoff_results
    ADD COLUMN IF NOT EXISTS incomplete_time_source_count integer NOT NULL DEFAULT 0
    CHECK (incomplete_time_source_count >= 0);

UPDATE payroll.employee_cutoff_results
SET incomplete_time_source_count = GREATEST(incomplete_time_source_count, 1)
WHERE paid_days > 0;

CREATE TABLE IF NOT EXISTS payroll.employee_compensations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    base_rate numeric(14, 2) NOT NULL CHECK (base_rate > 0),
    currency varchar(3) NOT NULL DEFAULT 'PHP' CHECK (currency ~ '^[A-Z]{3}$'),
    effective_from date NOT NULL,
    effective_to date,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_employee_compensations_effective_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS ix_employee_compensations_employee_group_period
    ON payroll.employee_compensations (employee_id, payroll_group_id, effective_from, effective_to);

CREATE TABLE IF NOT EXISTS payroll.earning_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    component_code varchar(30) NOT NULL CHECK (
        component_code IN (
            'REGULAR', 'PAID_LEAVE', 'OFFICIAL_BUSINESS', 'REST_DAY', 'SPECIAL_DAY',
            'HOLIDAY', 'ORDINARY_OT', 'REST_DAY_OT', 'SPECIAL_DAY_OT', 'HOLIDAY_OT',
            'NIGHT_REGULAR', 'NIGHT_OT'
        )
    ),
    multiplier numeric(8, 4) NOT NULL CHECK (multiplier >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT uq_payroll_earning_rules_group_component
        UNIQUE (payroll_group_id, component_code)
);

CREATE TABLE IF NOT EXISTS payroll.gross_pay_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cutoff_id uuid NOT NULL REFERENCES payroll.cutoffs(id),
    calculation_version varchar(50) NOT NULL,
    calculated_at timestamptz NOT NULL,
    calculated_by uuid NOT NULL REFERENCES identity.users(id),
    is_current boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_gross_pay_runs_current_cutoff
    ON payroll.gross_pay_runs (cutoff_id)
    WHERE is_current;

CREATE TABLE IF NOT EXISTS payroll.gross_pay_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES payroll.gross_pay_runs(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    cutoff_result_id uuid NOT NULL REFERENCES payroll.employee_cutoff_results(id),
    currency varchar(3),
    base_rate numeric(14, 2),
    gross_amount numeric(14, 2) CHECK (gross_amount IS NULL OR gross_amount >= 0),
    status varchar(20) NOT NULL CHECK (status IN ('HOLD', 'READY')),
    hold_reason text,
    earning_lines jsonb NOT NULL,
    source_minutes jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_payroll_gross_pay_results_run_employee UNIQUE (run_id, employee_id)
);

COMMIT;
