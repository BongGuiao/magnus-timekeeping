-- Regular-holiday pay attendance rule and unworked holiday pay components.
-- Mirrors alembic revision e1b2c3d4f5a6.
BEGIN;

ALTER TABLE payroll.company_system_parameters
    ADD COLUMN IF NOT EXISTS holiday_pay_attendance_rule varchar(20) NOT NULL DEFAULT 'BEFORE_ONLY';

ALTER TABLE payroll.company_system_parameters
    DROP CONSTRAINT IF EXISTS ck_payroll_company_system_parameters_holiday_pay_rule,
    ADD CONSTRAINT ck_payroll_company_system_parameters_holiday_pay_rule
        CHECK (holiday_pay_attendance_rule IN ('BEFORE_ONLY', 'BEFORE_AND_AFTER'));

ALTER TABLE payroll.employee_cutoff_results
    ADD COLUMN IF NOT EXISTS unworked_holiday_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unworked_double_holiday_minutes core.positive_minutes NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS disqualified_holiday_minutes core.positive_minutes NOT NULL DEFAULT 0;

ALTER TABLE payroll.earning_rules
    DROP CONSTRAINT IF EXISTS ck_payroll_earning_rules_component,
    ADD CONSTRAINT ck_payroll_earning_rules_component CHECK (
        component_code IN (
            'REGULAR', 'PAID_LEAVE', 'OFFICIAL_BUSINESS', 'REST_DAY', 'SPECIAL_DAY',
            'HOLIDAY', 'ORDINARY_OT', 'REST_DAY_OT', 'SPECIAL_DAY_OT', 'HOLIDAY_OT',
            'NIGHT_REGULAR', 'NIGHT_OT', 'UNWORKED_HOLIDAY', 'UNWORKED_DOUBLE_HOLIDAY'
        )
    );

-- Statutory unworked regular-holiday pay: 100% of the daily wage, 200% on a double holiday.
INSERT INTO payroll.earning_rules (payroll_group_id, component_code, multiplier, created_by, updated_by)
SELECT groups.payroll_group_id, rules.component_code, rules.multiplier, groups.created_by, groups.created_by
FROM (
    SELECT DISTINCT ON (payroll_group_id) payroll_group_id, created_by
    FROM payroll.earning_rules
    ORDER BY payroll_group_id, created_at
) AS groups
CROSS JOIN (
    VALUES ('UNWORKED_HOLIDAY', 1.0000), ('UNWORKED_DOUBLE_HOLIDAY', 2.0000)
) AS rules (component_code, multiplier)
ON CONFLICT (payroll_group_id, component_code) DO NOTHING;

COMMIT;
