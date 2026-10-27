BEGIN;

ALTER TABLE payroll.thirteenth_month_runs
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

COMMIT;
