-- Manual test-data seed, not a schema migration.
-- Run only against a development/test database after applying the payroll migrations.
-- This creates a dedicated demo company/group and synthetic employees.
-- It seeds approved cutoff summaries directly; it does not create raw punch records,
-- schedule assignments, or approval history. It uses existing active statutory
-- schedules and does not create or modify government rates.
--
-- To test two-cutoff contribution allocation, calculate DEMO-2026-10-A first,
-- then calculate DEMO-2026-10-B. Each payroll run must be started in the app.

BEGIN;

CREATE TEMP TABLE demo_payroll_context (
    actor_id uuid,
    company_id uuid,
    payroll_group_id uuid
) ON COMMIT DROP;

INSERT INTO demo_payroll_context DEFAULT VALUES;

DO $$
DECLARE
    v_actor_id uuid;
    v_schedule_count integer;
    v_bracket_count integer;
    v_program text;
    v_schedule_id uuid;
    v_cutoff_date date;
BEGIN
    IF to_regclass('payroll.employee_benefit_entitlements') IS NULL
       OR to_regclass('payroll.employee_benefit_deductions') IS NULL
       OR to_regclass('payroll.employee_cutoff_results') IS NULL THEN
        RAISE EXCEPTION
            'Required payroll tables are missing. Apply the payroll migrations before running this seed.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'payroll'
          AND table_name = 'benefit_types'
          AND column_name = 'posting_schedule'
    ) THEN
        RAISE EXCEPTION
            'Benefit posting schedule is not migrated. Apply the employee benefit entitlement migration first.';
    END IF;

    SELECT id
    INTO v_actor_id
    FROM identity.users
    WHERE is_active = true
      AND account_status = 'ACTIVE'
    ORDER BY created_at, id
    LIMIT 1;

    IF v_actor_id IS NULL THEN
        RAISE EXCEPTION
            'No active identity user is available for audit fields. Activate an admin user first.';
    END IF;

    UPDATE pg_temp.demo_payroll_context
    SET actor_id = v_actor_id;

    FOREACH v_program IN ARRAY ARRAY['SSS', 'PHILHEALTH', 'PAGIBIG']
    LOOP
        FOREACH v_cutoff_date IN ARRAY ARRAY[DATE '2026-10-15', DATE '2026-10-31']
        LOOP
            SELECT count(*)
            INTO v_schedule_count
            FROM payroll.statutory_contribution_schedules
            WHERE program_code = v_program
              AND status = 'ACTIVE'
              AND effective_from <= v_cutoff_date
              AND (effective_to IS NULL OR effective_to >= v_cutoff_date);

            IF v_schedule_count <> 1 THEN
                RAISE EXCEPTION
                    'Expected exactly one active % schedule effective %; found %.',
                    v_program, v_cutoff_date, v_schedule_count;
            END IF;

            SELECT id
            INTO v_schedule_id
            FROM payroll.statutory_contribution_schedules
            WHERE program_code = v_program
              AND status = 'ACTIVE'
              AND effective_from <= v_cutoff_date
              AND (effective_to IS NULL OR effective_to >= v_cutoff_date);

            SELECT count(*)
            INTO v_bracket_count
            FROM payroll.statutory_contribution_brackets
            WHERE schedule_id = v_schedule_id;

            IF v_bracket_count = 0 THEN
                RAISE EXCEPTION
                    'The active % schedule effective % has no brackets.',
                    v_program, v_cutoff_date;
            END IF;
        END LOOP;
    END LOOP;

    FOREACH v_cutoff_date IN ARRAY ARRAY[DATE '2026-10-15', DATE '2026-10-31']
    LOOP
        SELECT count(*)
        INTO v_schedule_count
        FROM payroll.withholding_tax_schedules
        WHERE status = 'ACTIVE'
          AND effective_from <= v_cutoff_date
          AND (effective_to IS NULL OR effective_to >= v_cutoff_date);

        IF v_schedule_count <> 1 THEN
            RAISE EXCEPTION
                'Expected exactly one active withholding-tax schedule effective %; found %.',
                v_cutoff_date, v_schedule_count;
        END IF;

        SELECT id
        INTO v_schedule_id
        FROM payroll.withholding_tax_schedules
        WHERE status = 'ACTIVE'
          AND effective_from <= v_cutoff_date
          AND (effective_to IS NULL OR effective_to >= v_cutoff_date);

        SELECT count(*)
        INTO v_bracket_count
        FROM payroll.withholding_tax_brackets
        WHERE schedule_id = v_schedule_id;

        IF v_bracket_count = 0 THEN
            RAISE EXCEPTION
                'The active withholding-tax schedule effective % has no brackets.',
                v_cutoff_date;
        END IF;
    END LOOP;
END
$$;

INSERT INTO core.companies (
    company_code, legal_name, trade_name, default_currency, status, is_active
)
VALUES (
    'DEMO-PAYROLL-3-2026',
    'Magnus Payroll Demo Company',
    'Payroll Demo',
    'PHP',
    'ACTIVE',
    true
)
ON CONFLICT (company_code) DO NOTHING;

UPDATE pg_temp.demo_payroll_context
SET company_id = company.id
FROM core.companies AS company
WHERE company.company_code = 'DEMO-PAYROLL-3-2026';

INSERT INTO payroll.payroll_groups (
    company_id,
    payroll_group_code,
    payroll_group_name,
    pay_frequency,
    rate_type,
    standard_minutes_per_day,
    annual_divisor,
    rounding_minutes,
    status,
    is_active
)
SELECT
    company_id,
    'DEMO-SEMIMONTHLY-2026',
    'Demo Semimonthly Payroll',
    'SEMIMONTHLY',
    'DAILY',
    480,
    260,
    1,
    'ACTIVE',
    true
FROM pg_temp.demo_payroll_context
ON CONFLICT (company_id, payroll_group_code) DO NOTHING;

UPDATE pg_temp.demo_payroll_context
SET payroll_group_id = payroll_group.id
FROM payroll.payroll_groups AS payroll_group
WHERE payroll_group.company_id = pg_temp.demo_payroll_context.company_id
  AND payroll_group.payroll_group_code = 'DEMO-SEMIMONTHLY-2026';

CREATE TEMP TABLE demo_payroll_people (
    employee_no varchar(30) PRIMARY KEY,
    first_name varchar(100) NOT NULL,
    last_name varchar(100) NOT NULL,
    daily_rate numeric(14, 2) NOT NULL,
    employee_id uuid
) ON COMMIT DROP;

INSERT INTO pg_temp.demo_payroll_people (
    employee_no, first_name, last_name, daily_rate
)
VALUES
    ('ZZ-DEMO-PAY-001', 'Alex', 'Santos', 1500.00),
    ('ZZ-DEMO-PAY-002', 'Blair', 'Reyes', 1200.00),
    ('ZZ-DEMO-PAY-003', 'Casey', 'Cruz', 1000.00);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_temp.demo_payroll_people AS demo
        JOIN hr.employees AS employee USING (employee_no)
        WHERE employee.first_name <> demo.first_name
           OR employee.last_name <> demo.last_name
    ) THEN
        RAISE EXCEPTION
            'A demo employee number already belongs to a different person. Review ZZ-DEMO-PAY-001..003 before rerunning.';
    END IF;
END
$$;

INSERT INTO hr.employees (
    employee_no, first_name, last_name, record_status, is_active
)
SELECT employee_no, first_name, last_name, 'ACTIVE', true
FROM pg_temp.demo_payroll_people
ON CONFLICT (employee_no) DO NOTHING;

UPDATE pg_temp.demo_payroll_people AS demo
SET employee_id = employee.id
FROM hr.employees AS employee
WHERE employee.employee_no = demo.employee_no;

INSERT INTO hr.employment_assignments (
    employee_id,
    company_id,
    employment_type,
    employee_category,
    payroll_group_id,
    hire_date,
    effective_from,
    status,
    is_active
)
SELECT
    demo.employee_id,
    context.company_id,
    'REGULAR',
    'FULL_TIME',
    context.payroll_group_id,
    DATE '2026-01-01',
    DATE '2026-01-01',
    'ACTIVE',
    true
FROM pg_temp.demo_payroll_people AS demo
CROSS JOIN pg_temp.demo_payroll_context AS context
WHERE NOT EXISTS (
    SELECT 1
    FROM hr.employment_assignments AS assignment
    WHERE assignment.employee_id = demo.employee_id
      AND assignment.payroll_group_id = context.payroll_group_id
      AND assignment.company_id = context.company_id
      AND assignment.is_active = true
      AND assignment.effective_from <= DATE '2026-10-01'
      AND (assignment.effective_to IS NULL OR assignment.effective_to >= DATE '2026-10-31')
);

INSERT INTO payroll.employee_compensations (
    employee_id,
    payroll_group_id,
    base_rate,
    currency,
    effective_from,
    is_active,
    created_by,
    updated_by
)
SELECT
    demo.employee_id,
    context.payroll_group_id,
    demo.daily_rate,
    'PHP',
    DATE '2026-01-01',
    true,
    context.actor_id,
    context.actor_id
FROM pg_temp.demo_payroll_people AS demo
CROSS JOIN pg_temp.demo_payroll_context AS context
WHERE NOT EXISTS (
    SELECT 1
    FROM payroll.employee_compensations AS compensation
    WHERE compensation.employee_id = demo.employee_id
      AND compensation.payroll_group_id = context.payroll_group_id
      AND compensation.is_active = true
      AND compensation.effective_from <= DATE '2026-10-01'
      AND (compensation.effective_to IS NULL OR compensation.effective_to >= DATE '2026-10-31')
);

INSERT INTO payroll.earning_rules AS current_rule (
    payroll_group_id, component_code, multiplier, created_by, updated_by
)
SELECT context.payroll_group_id, rules.component_code, rules.multiplier,
       context.actor_id, context.actor_id
FROM pg_temp.demo_payroll_context AS context
CROSS JOIN (VALUES
    ('REGULAR', 1.0000),
    ('PAID_LEAVE', 1.0000),
    ('OFFICIAL_BUSINESS', 1.0000),
    ('REST_DAY', 1.3000),
    ('SPECIAL_DAY', 1.3000),
    ('HOLIDAY', 2.0000),
    ('ORDINARY_OT', 1.2500),
    ('REST_DAY_OT', 1.6900),
    ('SPECIAL_DAY_OT', 1.6900),
    ('HOLIDAY_OT', 2.6000),
    ('NIGHT_REGULAR', 1.1000),
    ('NIGHT_OT', 1.3750)
) AS rules(component_code, multiplier)
ON CONFLICT (payroll_group_id, component_code)
DO UPDATE SET
    multiplier = EXCLUDED.multiplier,
    updated_by = EXCLUDED.updated_by,
    updated_at = now(),
    row_version = current_rule.row_version + 1;

INSERT INTO payroll.cutoffs (
    payroll_group_id, cutoff_code, period_start, period_end, pay_date, status, is_active
)
SELECT payroll_group_id, 'DEMO-2026-10-A', DATE '2026-10-01', DATE '2026-10-15',
       DATE '2026-10-20', 'SCHEDULED', true
FROM pg_temp.demo_payroll_context
ON CONFLICT (payroll_group_id, cutoff_code) DO NOTHING;

INSERT INTO payroll.cutoffs (
    payroll_group_id, cutoff_code, period_start, period_end, pay_date, status, is_active
)
SELECT payroll_group_id, 'DEMO-2026-10-B', DATE '2026-10-16', DATE '2026-10-31',
       DATE '2026-11-05', 'SCHEDULED', true
FROM pg_temp.demo_payroll_context
ON CONFLICT (payroll_group_id, cutoff_code) DO NOTHING;

CREATE TEMP TABLE demo_payroll_cutoffs (
    cutoff_code varchar(50) PRIMARY KEY,
    cutoff_id uuid
) ON COMMIT DROP;

INSERT INTO pg_temp.demo_payroll_cutoffs (cutoff_code)
VALUES ('DEMO-2026-10-A'), ('DEMO-2026-10-B');

UPDATE pg_temp.demo_payroll_cutoffs AS demo
SET cutoff_id = cutoff.id
FROM payroll.cutoffs AS cutoff
CROSS JOIN pg_temp.demo_payroll_context AS context
WHERE cutoff.payroll_group_id = context.payroll_group_id
  AND cutoff.cutoff_code = demo.cutoff_code;

INSERT INTO payroll.employee_cutoff_results (
    cutoff_id,
    employee_id,
    scheduled_days,
    paid_days,
    required_work_minutes,
    regular_minutes,
    late_minutes,
    undertime_minutes,
    ordinary_ot_minutes,
    employee_confirmation_status,
    supervisor_status,
    hr_status,
    payroll_status
)
SELECT
    demo_cutoff.cutoff_id,
    person.employee_id,
    facts.scheduled_days,
    facts.paid_days,
    facts.required_work_minutes,
    facts.regular_minutes,
    facts.late_minutes,
    facts.undertime_minutes,
    facts.ordinary_ot_minutes,
    'ACKNOWLEDGED',
    'ACKNOWLEDGED',
    'ACKNOWLEDGED',
    'HOLD'
FROM (VALUES
    ('DEMO-2026-10-A', 'ZZ-DEMO-PAY-001', 10, 10, 4800, 4800, 30, 15, 0),
    ('DEMO-2026-10-A', 'ZZ-DEMO-PAY-002', 10,  9, 4800, 4320,  0,  0, 0),
    ('DEMO-2026-10-A', 'ZZ-DEMO-PAY-003', 10, 10, 4800, 4800,  0,  0, 120),
    ('DEMO-2026-10-B', 'ZZ-DEMO-PAY-001', 10, 10, 4800, 4800, 20, 10, 0),
    ('DEMO-2026-10-B', 'ZZ-DEMO-PAY-002', 10,  8, 4800, 3840,  0,  0, 0),
    ('DEMO-2026-10-B', 'ZZ-DEMO-PAY-003', 10, 10, 4800, 4800,  0,  0, 60)
) AS facts(cutoff_code, employee_no, scheduled_days, paid_days,
           required_work_minutes, regular_minutes, late_minutes,
           undertime_minutes, ordinary_ot_minutes)
JOIN pg_temp.demo_payroll_cutoffs AS demo_cutoff USING (cutoff_code)
JOIN pg_temp.demo_payroll_people AS person USING (employee_no)
ON CONFLICT (cutoff_id, employee_id)
DO UPDATE SET
    scheduled_days = EXCLUDED.scheduled_days,
    paid_days = EXCLUDED.paid_days,
    required_work_minutes = EXCLUDED.required_work_minutes,
    regular_minutes = EXCLUDED.regular_minutes,
    late_minutes = EXCLUDED.late_minutes,
    undertime_minutes = EXCLUDED.undertime_minutes,
    ordinary_ot_minutes = EXCLUDED.ordinary_ot_minutes,
    employee_confirmation_status = EXCLUDED.employee_confirmation_status,
    supervisor_status = EXCLUDED.supervisor_status,
    hr_status = EXCLUDED.hr_status,
    payroll_status = EXCLUDED.payroll_status;

INSERT INTO payroll.benefit_types AS current_benefit_type (
    payroll_group_id, code, name, category, tax_treatment,
    attendance_based, deduct_for_late, deduct_for_undertime,
    posting_schedule, is_active, created_by, updated_by
)
SELECT context.payroll_group_id, benefit.code, benefit.name, benefit.category,
       benefit.tax_treatment, benefit.attendance_based, benefit.deduct_for_late,
       benefit.deduct_for_undertime, benefit.posting_schedule, true,
       context.actor_id, context.actor_id
FROM pg_temp.demo_payroll_context AS context
CROSS JOIN (VALUES
    ('DEMO-ATTENDANCE', 'Demo attendance allowance', 'CASH_ALLOWANCE',
     'EXEMPT', true, true, true, 'EVERY_CUTOFF'),
    ('DEMO-FIRST-HALF', 'Demo first-half bonus', 'ONE_TIME_BONUS',
     'TAXABLE', false, false, false, 'FIRST_HALF'),
    ('DEMO-SECOND-HALF', 'Demo second-half bonus', 'ONE_TIME_BONUS',
     'TAXABLE', false, false, false, 'SECOND_HALF'),
    ('DEMO-EMP-DEDUCTION', 'Demo recurring deduction', 'EMPLOYEE_DEDUCTION',
     'EXEMPT', false, false, false, 'EVERY_CUTOFF')
) AS benefit(code, name, category, tax_treatment,
             attendance_based, deduct_for_late, deduct_for_undertime, posting_schedule)
ON CONFLICT (payroll_group_id, code)
DO UPDATE SET
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    tax_treatment = EXCLUDED.tax_treatment,
    attendance_based = EXCLUDED.attendance_based,
    deduct_for_late = EXCLUDED.deduct_for_late,
    deduct_for_undertime = EXCLUDED.deduct_for_undertime,
    posting_schedule = EXCLUDED.posting_schedule,
    is_active = true,
    updated_by = EXCLUDED.updated_by,
    updated_at = now(),
    row_version = current_benefit_type.row_version + 1;

INSERT INTO payroll.employee_benefit_entitlements AS current_entitlement (
    employee_id, benefit_type_id, amount_per_occurrence,
    effective_from, is_active, created_by, updated_by
)
SELECT person.employee_id, benefit_type.id, entitlement.amount,
       DATE '2026-10-01', true, context.actor_id, context.actor_id
FROM (VALUES
    ('ZZ-DEMO-PAY-001', 'DEMO-ATTENDANCE', 1000.00),
    ('ZZ-DEMO-PAY-002', 'DEMO-ATTENDANCE',  800.00),
    ('ZZ-DEMO-PAY-003', 'DEMO-ATTENDANCE',  600.00),
    ('ZZ-DEMO-PAY-001', 'DEMO-FIRST-HALF',  300.00),
    ('ZZ-DEMO-PAY-002', 'DEMO-FIRST-HALF',  200.00),
    ('ZZ-DEMO-PAY-003', 'DEMO-FIRST-HALF',  150.00),
    ('ZZ-DEMO-PAY-001', 'DEMO-SECOND-HALF', 300.00),
    ('ZZ-DEMO-PAY-002', 'DEMO-SECOND-HALF', 200.00),
    ('ZZ-DEMO-PAY-003', 'DEMO-SECOND-HALF', 150.00)
) AS entitlement(employee_no, benefit_code, amount)
JOIN pg_temp.demo_payroll_people AS person USING (employee_no)
JOIN payroll.benefit_types AS benefit_type
  ON benefit_type.code = entitlement.benefit_code
CROSS JOIN pg_temp.demo_payroll_context AS context
WHERE benefit_type.payroll_group_id = context.payroll_group_id
ON CONFLICT (employee_id, benefit_type_id)
DO UPDATE SET
    amount_per_occurrence = EXCLUDED.amount_per_occurrence,
    effective_from = EXCLUDED.effective_from,
    effective_to = NULL,
    is_active = true,
    updated_by = EXCLUDED.updated_by,
    updated_at = now(),
    row_version = current_entitlement.row_version + 1;

INSERT INTO payroll.employee_benefit_deductions AS current_deduction (
    employee_id, benefit_type_id, amount_per_occurrence, schedule,
    effective_from, is_active, created_by, updated_by
)
SELECT person.employee_id, benefit_type.id, deduction.amount,
       deduction.schedule, DATE '2026-10-01', true, context.actor_id, context.actor_id
FROM (VALUES
    ('ZZ-DEMO-PAY-001', 100.00, 'EVERY_CUTOFF'),
    ('ZZ-DEMO-PAY-002', 150.00, 'FIRST_HALF'),
    ('ZZ-DEMO-PAY-003', 200.00, 'SECOND_HALF')
) AS deduction(employee_no, amount, schedule)
JOIN pg_temp.demo_payroll_people AS person USING (employee_no)
CROSS JOIN pg_temp.demo_payroll_context AS context
JOIN payroll.benefit_types AS benefit_type
  ON benefit_type.payroll_group_id = context.payroll_group_id
 AND benefit_type.code = 'DEMO-EMP-DEDUCTION'
ON CONFLICT (employee_id, benefit_type_id)
DO UPDATE SET
    amount_per_occurrence = EXCLUDED.amount_per_occurrence,
    schedule = EXCLUDED.schedule,
    effective_from = EXCLUDED.effective_from,
    effective_to = NULL,
    is_active = true,
    updated_by = EXCLUDED.updated_by,
    updated_at = now(),
    row_version = current_deduction.row_version + 1;

INSERT INTO payroll.opening_ytd_balances (
    employee_id, tax_year, taxable_income, tax_withheld,
    exempt_limited_benefits, created_by
)
SELECT person.employee_id, 2026, 0, 0, 0, context.actor_id
FROM pg_temp.demo_payroll_people AS person
CROSS JOIN pg_temp.demo_payroll_context AS context
WHERE NOT EXISTS (
    SELECT 1
    FROM payroll.opening_ytd_balances AS opening
    WHERE opening.employee_id = person.employee_id
      AND opening.tax_year = 2026
      AND opening.previous_balance_id IS NULL
);

-- Review the created demo records and their IDs.
SELECT employee_no, first_name, last_name, employee_id
FROM pg_temp.demo_payroll_people
ORDER BY employee_no;

SELECT cutoff_code, cutoff_id
FROM pg_temp.demo_payroll_cutoffs
ORDER BY cutoff_code;

COMMIT;
