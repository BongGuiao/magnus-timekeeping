BEGIN;

ALTER TABLE payroll.statutory_contribution_brackets
    ADD COLUMN employee_contribution_cap numeric(14, 2),
    ADD COLUMN employer_contribution_cap numeric(14, 2);

ALTER TABLE payroll.statutory_contribution_brackets
    ADD CONSTRAINT ck_payroll_contribution_caps
    CHECK (
        (employee_contribution_cap IS NULL OR employee_contribution_cap >= 0)
        AND (employer_contribution_cap IS NULL OR employer_contribution_cap >= 0)
    );

ALTER TABLE payroll.withholding_tax_schedules
    ADD COLUMN calculation_basis varchar(20) NOT NULL DEFAULT 'ANNUAL_YTD';

ALTER TABLE payroll.withholding_tax_schedules
    ADD CONSTRAINT ck_payroll_withholding_tax_calculation_basis
    CHECK (calculation_basis IN ('ANNUAL_YTD', 'SEMI_MONTHLY'));

ALTER TABLE payroll.withholding_tax_schedules
    ALTER COLUMN calculation_basis SET DEFAULT 'SEMI_MONTHLY';

COMMIT;
