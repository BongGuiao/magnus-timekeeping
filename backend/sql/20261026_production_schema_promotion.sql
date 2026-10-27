-- Apply to a database matching the 2026-10-26 production backup.
-- This is an additive schema/permission migration. It does not copy application
-- records or user-role assignments and intentionally retains production-only
-- payroll deadline columns and schedule-upload constraints.
--
-- Do not run 20261023_payroll_cutoff_single_attendance_deadline.sql as part of
-- this promotion: that migration drops the three production deadline columns.
BEGIN;

CREATE SCHEMA IF NOT EXISTS payroll;

ALTER TABLE payroll.cutoffs
    ADD COLUMN IF NOT EXISTS attendance_deadline timestamptz,
    ADD COLUMN IF NOT EXISTS cutoff_half varchar(20);

DO $$
DECLARE
    deadline_columns text;
BEGIN
    SELECT string_agg(
        format('%I', column_name),
        ', ' ORDER BY array_position(
            ARRAY[
                'employee_review_deadline',
                'supervisor_deadline',
                'hr_deadline'
            ],
            column_name
        )
    )
    INTO deadline_columns
    FROM information_schema.columns
    WHERE table_schema = 'payroll'
      AND table_name = 'cutoffs'
      AND column_name IN (
          'employee_review_deadline',
          'supervisor_deadline',
          'hr_deadline'
      );

    IF deadline_columns IS NOT NULL THEN
        EXECUTE format(
            'UPDATE payroll.cutoffs
             SET attendance_deadline = GREATEST(%s)
             WHERE attendance_deadline IS NULL',
            deadline_columns
        );
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_cutoffs_cutoff_half'
          AND conrelid = 'payroll.cutoffs'::regclass
    ) THEN
        ALTER TABLE payroll.cutoffs
            ADD CONSTRAINT ck_cutoffs_cutoff_half
            CHECK (
                cutoff_half IS NULL
                OR cutoff_half IN ('FIRST_HALF', 'SECOND_HALF')
            );
    END IF;
END;
$$;

ALTER TABLE payroll.benefit_types
    ADD COLUMN IF NOT EXISTS withholding_timing varchar(20)
        NOT NULL DEFAULT 'PAY_PERIOD';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_benefit_type_withholding_timing'
          AND conrelid = 'payroll.benefit_types'::regclass
    ) THEN
        ALTER TABLE payroll.benefit_types
            ADD CONSTRAINT ck_payroll_benefit_type_withholding_timing
            CHECK (
                withholding_timing = 'PAY_PERIOD'
                OR (
                    withholding_timing = 'YEAR_END'
                    AND category = 'ONE_TIME_BONUS'
                    AND tax_treatment = 'TAXABLE'
                )
            );
    END IF;
END;
$$;

ALTER TABLE payroll.cutoff_benefits
    ADD COLUMN IF NOT EXISTS withholding_timing varchar(20)
        NOT NULL DEFAULT 'PAY_PERIOD';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_cutoff_benefit_withholding_timing'
          AND conrelid = 'payroll.cutoff_benefits'::regclass
    ) THEN
        ALTER TABLE payroll.cutoff_benefits
            ADD CONSTRAINT ck_payroll_cutoff_benefit_withholding_timing
            CHECK (
                withholding_timing = 'PAY_PERIOD'
                OR (
                    withholding_timing = 'YEAR_END'
                    AND category = 'ONE_TIME_BONUS'
                    AND tax_treatment = 'TAXABLE'
                )
            );
    END IF;
END;
$$;

ALTER TABLE payroll.employee_benefit_entitlements
    ADD COLUMN IF NOT EXISTS schedule varchar(20);

UPDATE payroll.employee_benefit_entitlements AS entitlement
SET schedule = benefit_type.posting_schedule
FROM payroll.benefit_types AS benefit_type
WHERE benefit_type.id = entitlement.benefit_type_id
  AND entitlement.schedule IS NULL;

UPDATE payroll.employee_benefit_entitlements
SET schedule = 'EVERY_CUTOFF'
WHERE schedule IS NULL;

ALTER TABLE payroll.employee_benefit_entitlements
    ALTER COLUMN schedule SET DEFAULT 'EVERY_CUTOFF',
    ALTER COLUMN schedule SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_employee_benefit_entitlement_schedule'
          AND conrelid = 'payroll.employee_benefit_entitlements'::regclass
    ) THEN
        ALTER TABLE payroll.employee_benefit_entitlements
            ADD CONSTRAINT ck_employee_benefit_entitlement_schedule
            CHECK (schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF'));
    END IF;
END;
$$;

ALTER TABLE payroll.statutory_contribution_brackets
    ADD COLUMN IF NOT EXISTS employee_contribution_cap numeric(14, 2),
    ADD COLUMN IF NOT EXISTS employer_contribution_cap numeric(14, 2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_contribution_caps'
          AND conrelid = 'payroll.statutory_contribution_brackets'::regclass
    ) THEN
        ALTER TABLE payroll.statutory_contribution_brackets
            ADD CONSTRAINT ck_payroll_contribution_caps
            CHECK (
                (employee_contribution_cap IS NULL OR employee_contribution_cap >= 0)
                AND (employer_contribution_cap IS NULL OR employer_contribution_cap >= 0)
            );
    END IF;
END;
$$;

ALTER TABLE payroll.withholding_tax_schedules
    ADD COLUMN IF NOT EXISTS calculation_basis varchar(20)
        NOT NULL DEFAULT 'ANNUAL_YTD';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_withholding_tax_calculation_basis'
          AND conrelid = 'payroll.withholding_tax_schedules'::regclass
    ) THEN
        ALTER TABLE payroll.withholding_tax_schedules
            ADD CONSTRAINT ck_payroll_withholding_tax_calculation_basis
            CHECK (calculation_basis IN ('ANNUAL_YTD', 'SEMI_MONTHLY'));
    END IF;
END;
$$;

ALTER TABLE payroll.withholding_tax_schedules
    ALTER COLUMN calculation_basis SET DEFAULT 'SEMI_MONTHLY';

CREATE TABLE IF NOT EXISTS payroll.system_parameters (
    id smallint PRIMARY KEY DEFAULT 1,
    year_end_wtax_reconciliation_enabled boolean NOT NULL DEFAULT false,
    thirteenth_month_enabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES identity.users(id),
    CONSTRAINT ck_payroll_system_parameters_singleton CHECK (id = 1)
);

ALTER TABLE payroll.system_parameters
    ADD COLUMN IF NOT EXISTS year_end_wtax_reconciliation_enabled
        boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS thirteenth_month_enabled
        boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_by uuid REFERENCES identity.users(id);

INSERT INTO payroll.system_parameters (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS payroll.company_system_parameters (
    company_id uuid PRIMARY KEY
        REFERENCES core.companies(id) ON DELETE CASCADE,
    year_end_wtax_reconciliation_enabled boolean NOT NULL DEFAULT false,
    thirteenth_month_enabled boolean NOT NULL DEFAULT false,
    statutory_contribution_timing varchar(20) NOT NULL DEFAULT 'PER_CUTOFF',
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES identity.users(id),
    schedule_assignment_approval_required boolean NOT NULL DEFAULT true,
    CONSTRAINT ck_payroll_company_system_parameters_contribution_timing
        CHECK (statutory_contribution_timing IN ('PER_CUTOFF', 'FINAL_CUTOFF'))
);

ALTER TABLE payroll.company_system_parameters
    ADD COLUMN IF NOT EXISTS year_end_wtax_reconciliation_enabled
        boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS thirteenth_month_enabled
        boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS statutory_contribution_timing
        varchar(20) NOT NULL DEFAULT 'PER_CUTOFF',
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_by uuid REFERENCES identity.users(id),
    ADD COLUMN IF NOT EXISTS schedule_assignment_approval_required
        boolean NOT NULL DEFAULT true;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_company_system_parameters_contribution_timing'
          AND conrelid = 'payroll.company_system_parameters'::regclass
    ) THEN
        ALTER TABLE payroll.company_system_parameters
            ADD CONSTRAINT ck_payroll_company_system_parameters_contribution_timing
            CHECK (statutory_contribution_timing IN ('PER_CUTOFF', 'FINAL_CUTOFF'));
    END IF;
END;
$$;

-- Create company-scoped rows with application defaults; no local settings are copied.
INSERT INTO payroll.company_system_parameters (company_id)
SELECT company.id
FROM core.companies AS company
ON CONFLICT (company_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS payroll.thirteenth_month_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tax_year integer NOT NULL CHECK (tax_year BETWEEN 1900 AND 9999),
    calculated_at timestamptz NOT NULL,
    calculated_by uuid NOT NULL REFERENCES identity.users(id),
    is_current boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    company_id uuid REFERENCES core.companies(id),
    covered_period_from date,
    covered_period_to date,
    CONSTRAINT ck_payroll_thirteenth_month_covered_period CHECK (
        (covered_period_from IS NULL AND covered_period_to IS NULL)
        OR (
            covered_period_from IS NOT NULL
            AND covered_period_to IS NOT NULL
            AND covered_period_from <= covered_period_to
            AND EXTRACT(YEAR FROM covered_period_from) = tax_year
            AND EXTRACT(YEAR FROM covered_period_to) = tax_year
        )
    )
);

ALTER TABLE payroll.thirteenth_month_runs
    ADD COLUMN IF NOT EXISTS company_id uuid REFERENCES core.companies(id),
    ADD COLUMN IF NOT EXISTS covered_period_from date,
    ADD COLUMN IF NOT EXISTS covered_period_to date;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_payroll_thirteenth_month_covered_period'
          AND conrelid = 'payroll.thirteenth_month_runs'::regclass
    ) THEN
        ALTER TABLE payroll.thirteenth_month_runs
            ADD CONSTRAINT ck_payroll_thirteenth_month_covered_period
            CHECK (
                (covered_period_from IS NULL AND covered_period_to IS NULL)
                OR (
                    covered_period_from IS NOT NULL
                    AND covered_period_to IS NOT NULL
                    AND covered_period_from <= covered_period_to
                    AND EXTRACT(YEAR FROM covered_period_from) = tax_year
                    AND EXTRACT(YEAR FROM covered_period_to) = tax_year
                )
            );
    END IF;
END;
$$;

DROP INDEX IF EXISTS payroll.uq_payroll_thirteenth_month_current_year;

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_thirteenth_month_current_year
    ON payroll.thirteenth_month_runs (company_id, tax_year)
    WHERE is_current AND company_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS payroll.thirteenth_month_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL
        REFERENCES payroll.thirteenth_month_runs(id) ON DELETE CASCADE,
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
    CONSTRAINT uq_payroll_thirteenth_month_result_employee
        UNIQUE (run_id, employee_id)
);

CREATE TABLE IF NOT EXISTS payroll.employee_loans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    reference_number varchar(50) NOT NULL,
    principal_amount numeric(14, 2) NOT NULL,
    installment_amount numeric(14, 2) NOT NULL,
    schedule varchar(20) NOT NULL,
    effective_from date NOT NULL,
    outstanding_balance numeric(14, 2) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'ACTIVE',
    previous_loan_id uuid REFERENCES payroll.employee_loans(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES identity.users(id),
    CONSTRAINT uq_employee_loan_reference_number UNIQUE (reference_number),
    CONSTRAINT ck_employee_loan_principal CHECK (principal_amount > 0),
    CONSTRAINT ck_employee_loan_installment CHECK (installment_amount > 0),
    CONSTRAINT ck_employee_loan_schedule
        CHECK (schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF')),
    CONSTRAINT ck_employee_loan_balance CHECK (outstanding_balance >= 0),
    CONSTRAINT ck_employee_loan_status
        CHECK (status IN ('ACTIVE', 'RETIRED', 'PAID_OFF'))
);

CREATE TABLE IF NOT EXISTS payroll.employee_loan_repayments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id uuid NOT NULL REFERENCES payroll.employee_loans(id),
    cutoff_id uuid NOT NULL REFERENCES payroll.cutoffs(id),
    gross_pay_run_id uuid NOT NULL REFERENCES payroll.gross_pay_runs(id),
    amount numeric(14, 2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_employee_loan_repayment_amount CHECK (amount > 0),
    CONSTRAINT uq_employee_loan_repayment_cutoff UNIQUE (loan_id, cutoff_id)
);

CREATE TABLE IF NOT EXISTS payroll.off_cycle_payroll_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES core.companies(id),
    payroll_group_id uuid NOT NULL REFERENCES payroll.payroll_groups(id),
    benefit_type_id uuid NOT NULL REFERENCES payroll.benefit_types(id),
    thirteenth_month_run_id uuid
        REFERENCES payroll.thirteenth_month_runs(id),
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
            (
                run_type = 'BENEFIT'
                AND benefit_type_id IS NOT NULL
                AND thirteenth_month_run_id IS NULL
            )
            OR (
                run_type = 'THIRTEENTH_MONTH'
                AND benefit_type_id IS NOT NULL
                AND thirteenth_month_run_id IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS ix_off_cycle_payroll_run_paid_company_date
    ON payroll.off_cycle_payroll_runs (company_id, actual_payment_date)
    WHERE status = 'PAID';

CREATE TABLE IF NOT EXISTS payroll.off_cycle_payroll_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL
        REFERENCES payroll.off_cycle_payroll_runs(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    thirteenth_month_result_id uuid
        REFERENCES payroll.thirteenth_month_results(id),
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
            taxable_amount >= 0
            AND exempt_limited_amount >= 0
            AND withholding_tax >= 0
            AND net_amount >= 0
        ),
    CONSTRAINT uq_off_cycle_payroll_line_run_employee
        UNIQUE (run_id, employee_id)
);

CREATE INDEX IF NOT EXISTS ix_off_cycle_payroll_line_13m_result
    ON payroll.off_cycle_payroll_lines (thirteenth_month_result_id);
CREATE INDEX IF NOT EXISTS ix_off_cycle_payroll_line_employee
    ON payroll.off_cycle_payroll_lines (employee_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'org_unit_types'
          AND column_name = 'company_id'
    ) AND to_regclass('core.org_unit_types') IS NOT NULL THEN
        RAISE EXCEPTION
            'core.org_unit_types exists without company_id; run the reviewed company-scoping upgrade separately.';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS core.org_unit_types (
    company_id uuid NOT NULL,
    org_unit_type varchar(30) NOT NULL,
    display_name varchar(50) NOT NULL,
    sort_order integer NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT pk_org_unit_types PRIMARY KEY (company_id, org_unit_type),
    CONSTRAINT fk_org_unit_types_company
        FOREIGN KEY (company_id) REFERENCES core.companies(id) ON DELETE CASCADE,
    CONSTRAINT ck_org_unit_types_code_not_empty
        CHECK (length(btrim(org_unit_type)) > 0),
    CONSTRAINT ck_org_unit_types_display_name_not_empty
        CHECK (length(btrim(display_name)) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_org_unit_types_single_default_per_company
    ON core.org_unit_types (company_id)
    WHERE is_default;

INSERT INTO core.org_unit_types (
    company_id,
    org_unit_type,
    display_name,
    sort_order,
    is_default,
    is_active
)
SELECT
    company.id,
    type.org_unit_type,
    type.display_name,
    type.sort_order,
    type.org_unit_type = 'DEPARTMENT'
        AND NOT EXISTS (
            SELECT 1
            FROM core.org_unit_types AS existing
            WHERE existing.company_id = company.id
              AND existing.is_default
        ),
    true
FROM core.companies AS company
CROSS JOIN (
    VALUES
        ('DIVISION', 'Division', 10),
        ('DEPARTMENT', 'Department', 20),
        ('TEAM', 'Team', 30),
        ('BRANCH', 'Branch', 40),
        ('COST_CENTER', 'Cost center', 50)
) AS type(org_unit_type, display_name, sort_order)
ON CONFLICT (company_id, org_unit_type) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_schedule_upload_batches_no_self_approval'
          AND conrelid = 'schedule.schedule_upload_batches'::regclass
    ) THEN
        ALTER TABLE schedule.schedule_upload_batches
            ADD CONSTRAINT ck_schedule_upload_batches_no_self_approval
            CHECK (status <> 'APPROVED' OR reviewed_by <> uploaded_by);
    END IF;
END;
$$;

INSERT INTO identity.permissions (
    permission_code,
    module_code,
    action_code,
    permission_name,
    description
)
VALUES
    (
        'employees.read_team',
        'employees',
        'read_team',
        'View team employees',
        'View employee records of current direct reports only.'
    ),
    (
        'payroll.approve',
        'payroll',
        'approve',
        'Approve and finalize payroll',
        'Approve calculated payroll cutoffs after all employee results are ready.'
    ),
    (
        'payroll.company_parameters.manage',
        'payroll',
        'company_parameters_manage',
        'Manage company payroll parameters',
        'Manage company-scoped payroll calculation and statutory deduction settings.'
    )
ON CONFLICT (permission_code) DO UPDATE
SET
    module_code = EXCLUDED.module_code,
    action_code = EXCLUDED.action_code,
    permission_name = EXCLUDED.permission_name,
    description = EXCLUDED.description,
    is_active = true;

DELETE FROM identity.role_permissions AS role_permission
USING identity.roles AS role_row, identity.permissions AS permission_row
WHERE role_permission.role_id = role_row.id
  AND role_permission.permission_id = permission_row.id
  AND upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR')
  AND permission_row.permission_code LIKE 'payroll.%';

INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
SELECT role_row.id, permission_row.id, true
FROM identity.roles AS role_row
CROSS JOIN identity.permissions AS permission_row
WHERE (
        upper(role_row.role_code) = 'HR_ADMIN'
        AND permission_row.permission_code IN (
            'payroll.approve',
            'payroll.company_parameters.manage'
        )
    )
    OR (
        upper(role_row.role_code) = 'PAYROLL_HEAD'
        AND permission_row.permission_code = 'payroll.approve'
    )
    OR (
        upper(role_row.role_code) = 'SUPERVISOR'
        AND permission_row.permission_code = 'employees.read_team'
    )
ON CONFLICT (role_id, permission_id)
DO UPDATE SET allowed = EXCLUDED.allowed;

DELETE FROM identity.role_permissions AS role_permission
USING identity.roles AS role_row, identity.permissions AS permission_row
WHERE role_permission.role_id = role_row.id
  AND role_permission.permission_id = permission_row.id
  AND upper(role_row.role_code) = 'SUPERVISOR'
  AND permission_row.permission_code = 'employees.read';

COMMIT;

-- Verification: this must return no rows.
SELECT role_row.role_code, permission_row.permission_code
FROM identity.role_permissions AS role_permission
JOIN identity.roles AS role_row ON role_row.id = role_permission.role_id
JOIN identity.permissions AS permission_row
    ON permission_row.id = role_permission.permission_id
WHERE upper(role_row.role_code) IN ('SYSTEM_ADMIN', 'SYSTEM_ADMINISTRATOR')
  AND role_permission.allowed
  AND permission_row.permission_code LIKE 'payroll.%';
