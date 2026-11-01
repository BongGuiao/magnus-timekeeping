-- Mirrors Alembic revision f2c3d4e5a6b7.
-- NULL preserves the existing attendance_deadline for both filing and approval.
BEGIN;

ALTER TABLE payroll.cutoffs
    ADD COLUMN IF NOT EXISTS employee_filing_deadline timestamptz;

ALTER TABLE payroll.cutoffs
    DROP CONSTRAINT IF EXISTS ck_cutoffs_filing_before_approval,
    ADD CONSTRAINT ck_cutoffs_filing_before_approval CHECK (
        employee_filing_deadline IS NULL OR (
            attendance_deadline IS NOT NULL AND employee_filing_deadline <= attendance_deadline
        )
    );

COMMIT;
