BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_assignment_payroll_group'
          AND conrelid = 'hr.employment_assignments'::regclass
    ) THEN
        ALTER TABLE hr.employment_assignments
            ADD CONSTRAINT fk_assignment_payroll_group
            FOREIGN KEY (payroll_group_id)
            REFERENCES payroll.payroll_groups(id);
    END IF;
END;
$$;

COMMIT;
