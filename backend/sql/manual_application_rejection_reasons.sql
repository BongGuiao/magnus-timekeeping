-- For existing untracked databases only. Run with psql -v ON_ERROR_STOP=1.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE tracked boolean;
BEGIN
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.alembic_version)' INTO tracked;
        IF tracked THEN
            RAISE EXCEPTION 'Use Alembic for this tracked database, not the manual script.';
        END IF;
    END IF;
    IF to_regclass('leave_mgmt.leave_applications') IS NULL
       OR to_regclass('attendance.overtime_applications') IS NULL
       OR to_regclass('attendance.official_business_requests') IS NULL THEN
        RAISE EXCEPTION 'A required application table is missing.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE column_name = 'rejection_reason'
          AND (table_schema, table_name) IN (
              ('leave_mgmt', 'leave_applications'),
              ('attendance', 'overtime_applications'),
              ('attendance', 'official_business_requests')
          )
    ) THEN
        RAISE EXCEPTION 'A rejection reason column already exists; review the schema first.';
    END IF;
END $$;

ALTER TABLE leave_mgmt.leave_applications ADD COLUMN rejection_reason text;
ALTER TABLE attendance.overtime_applications ADD COLUMN rejection_reason text;
ALTER TABLE attendance.official_business_requests ADD COLUMN rejection_reason text;
COMMIT;
