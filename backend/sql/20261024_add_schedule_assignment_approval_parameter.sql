BEGIN;

ALTER TABLE payroll.company_system_parameters
    ADD COLUMN IF NOT EXISTS schedule_assignment_approval_required boolean NOT NULL DEFAULT true;

COMMIT;
