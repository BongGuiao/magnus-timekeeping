-- One attendance deadline per payroll cutoff replaces the employee, supervisor and HR deadlines.
-- After it passes, attendance, overtime and official business covered by the cutoff can no
-- longer be filed, changed or approved. Late leave may still be approved and paid in the next cutoff.
BEGIN;

ALTER TABLE payroll.cutoffs
    ADD COLUMN IF NOT EXISTS attendance_deadline timestamptz;

-- Backfill only while the old columns still exist, so the script can be rerun safely.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'payroll'
          AND table_name = 'cutoffs'
          AND column_name = 'employee_review_deadline'
    ) THEN
        EXECUTE '
            UPDATE payroll.cutoffs
            SET attendance_deadline = GREATEST(employee_review_deadline, supervisor_deadline, hr_deadline)
            WHERE attendance_deadline IS NULL';
    END IF;
END $$;

ALTER TABLE payroll.cutoffs
    DROP COLUMN IF EXISTS employee_review_deadline,
    DROP COLUMN IF EXISTS supervisor_deadline,
    DROP COLUMN IF EXISTS hr_deadline;

COMMIT;
