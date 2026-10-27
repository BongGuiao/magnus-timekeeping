BEGIN;

ALTER TABLE payroll.employee_benefit_entitlements
    ADD COLUMN IF NOT EXISTS schedule varchar(20);

UPDATE payroll.employee_benefit_entitlements AS entitlement
SET schedule = benefit_type.posting_schedule
FROM payroll.benefit_types AS benefit_type
WHERE benefit_type.id = entitlement.benefit_type_id
  AND entitlement.schedule IS NULL;

UPDATE payroll.employee_benefit_entitlements
SET schedule = 'EVERY_CUTOFF'
WHERE schedule IS NULL;

ALTER TABLE payroll.employee_benefit_entitlements
    ALTER COLUMN schedule SET DEFAULT 'EVERY_CUTOFF',
    ALTER COLUMN schedule SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_employee_benefit_entitlement_schedule'
          AND conrelid = 'payroll.employee_benefit_entitlements'::regclass
    ) THEN
        ALTER TABLE payroll.employee_benefit_entitlements
            ADD CONSTRAINT ck_employee_benefit_entitlement_schedule
            CHECK (schedule IN ('FIRST_HALF', 'SECOND_HALF', 'EVERY_CUTOFF'));
    END IF;
END $$;

COMMIT;
