BEGIN;

ALTER TABLE payroll.benefit_types
    ADD COLUMN withholding_timing varchar(20) NOT NULL DEFAULT 'PAY_PERIOD';

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

ALTER TABLE payroll.cutoff_benefits
    ADD COLUMN withholding_timing varchar(20) NOT NULL DEFAULT 'PAY_PERIOD';

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

COMMIT;
