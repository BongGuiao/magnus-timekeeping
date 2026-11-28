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
    IF to_regnamespace('leave_mgmt') IS NULL OR to_regclass('core.companies') IS NULL THEN
        RAISE EXCEPTION 'Required schema or company table is missing.';
    END IF;
    IF to_regclass('leave_mgmt.leave_computation_matrices') IS NOT NULL THEN
        RAISE EXCEPTION 'The matrix table already exists; review the schema first.';
    END IF;
END $$;

CREATE TABLE leave_mgmt.leave_computation_matrices (
    company_id uuid PRIMARY KEY REFERENCES core.companies(id),
    ranges jsonb NOT NULL,
    row_version integer NOT NULL DEFAULT 1
);
COMMIT;
