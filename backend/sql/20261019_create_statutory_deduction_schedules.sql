BEGIN;

CREATE TABLE IF NOT EXISTS payroll.statutory_contribution_schedules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_code varchar(20) NOT NULL CHECK (
        program_code IN ('SSS', 'PHILHEALTH', 'PAGIBIG')
    ),
    schedule_name varchar(120) NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    source_reference text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT', 'ACTIVE', 'RETIRED')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_payroll_statutory_contribution_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT uq_payroll_statutory_contribution_period
        UNIQUE (program_code, effective_from)
);

CREATE TABLE IF NOT EXISTS payroll.statutory_contribution_brackets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id uuid NOT NULL REFERENCES payroll.statutory_contribution_schedules(id)
        ON DELETE CASCADE,
    bracket_number integer NOT NULL CHECK (bracket_number > 0),
    compensation_min numeric(14, 2) NOT NULL CHECK (compensation_min >= 0),
    compensation_max numeric(14, 2),
    contribution_base numeric(14, 2) NOT NULL DEFAULT 0 CHECK (contribution_base >= 0),
    employee_rate numeric(8, 6) NOT NULL DEFAULT 0 CHECK (employee_rate BETWEEN 0 AND 1),
    employer_rate numeric(8, 6) NOT NULL DEFAULT 0 CHECK (employer_rate BETWEEN 0 AND 1),
    employee_fixed_amount numeric(14, 2) NOT NULL DEFAULT 0 CHECK (employee_fixed_amount >= 0),
    employer_fixed_amount numeric(14, 2) NOT NULL DEFAULT 0 CHECK (employer_fixed_amount >= 0),
    employer_additional_fixed_amount numeric(14, 2) NOT NULL DEFAULT 0
        CHECK (employer_additional_fixed_amount >= 0),
    CONSTRAINT ck_payroll_contribution_max
        CHECK (compensation_max IS NULL OR compensation_max >= compensation_min),
    CONSTRAINT uq_payroll_contribution_bracket_number
        UNIQUE (schedule_id, bracket_number),
    CONSTRAINT uq_payroll_contribution_bracket_min
        UNIQUE (schedule_id, compensation_min)
);

CREATE TABLE IF NOT EXISTS payroll.withholding_tax_schedules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_name varchar(120) NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    tax_exempt_benefit_limit numeric(14, 2) NOT NULL
        CHECK (tax_exempt_benefit_limit >= 0),
    source_reference text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT', 'ACTIVE', 'RETIRED')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid REFERENCES identity.users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES identity.users(id),
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_payroll_withholding_tax_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT uq_payroll_withholding_tax_period UNIQUE (effective_from)
);

CREATE TABLE IF NOT EXISTS payroll.withholding_tax_brackets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id uuid NOT NULL REFERENCES payroll.withholding_tax_schedules(id)
        ON DELETE CASCADE,
    bracket_number integer NOT NULL CHECK (bracket_number > 0),
    annual_income_min numeric(14, 2) NOT NULL CHECK (annual_income_min >= 0),
    annual_income_max numeric(14, 2),
    base_tax numeric(14, 2) NOT NULL CHECK (base_tax >= 0),
    marginal_rate numeric(8, 6) NOT NULL CHECK (marginal_rate BETWEEN 0 AND 1),
    excess_over numeric(14, 2) NOT NULL CHECK (excess_over >= 0),
    CONSTRAINT ck_payroll_tax_bracket_max
        CHECK (annual_income_max IS NULL OR annual_income_max >= annual_income_min),
    CONSTRAINT uq_payroll_tax_bracket_number
        UNIQUE (schedule_id, bracket_number),
    CONSTRAINT uq_payroll_tax_bracket_min
        UNIQUE (schedule_id, annual_income_min)
);

CREATE INDEX IF NOT EXISTS ix_payroll_contribution_schedules_effective
    ON payroll.statutory_contribution_schedules (program_code, effective_from, effective_to);

CREATE INDEX IF NOT EXISTS ix_payroll_contribution_brackets_schedule
    ON payroll.statutory_contribution_brackets (schedule_id, compensation_min);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_contribution_bracket_open_ended
    ON payroll.statutory_contribution_brackets (schedule_id)
    WHERE compensation_max IS NULL;

CREATE INDEX IF NOT EXISTS ix_payroll_tax_schedules_effective
    ON payroll.withholding_tax_schedules (effective_from, effective_to);

CREATE INDEX IF NOT EXISTS ix_payroll_tax_brackets_schedule
    ON payroll.withholding_tax_brackets (schedule_id, annual_income_min);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_tax_bracket_open_ended
    ON payroll.withholding_tax_brackets (schedule_id)
    WHERE annual_income_max IS NULL;

COMMIT;
