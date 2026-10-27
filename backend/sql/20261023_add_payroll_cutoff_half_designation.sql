BEGIN;

ALTER TABLE payroll.cutoffs
    ADD COLUMN IF NOT EXISTS cutoff_half VARCHAR(20);

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
            CHECK (cutoff_half IS NULL OR cutoff_half IN ('FIRST_HALF', 'SECOND_HALF'));
    END IF;
END
$$;

COMMIT;
