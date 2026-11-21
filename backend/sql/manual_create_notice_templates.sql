-- For existing databases without Alembic revision tracking.
-- Back up and review the target schema before running this script.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    tracked boolean;
BEGIN
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.alembic_version)' INTO tracked;
        IF tracked THEN
            RAISE EXCEPTION 'Use Alembic for this tracked database, not the manual script.';
        END IF;
    END IF;
    IF to_regnamespace('attendance') IS NULL THEN
        RAISE EXCEPTION 'The attendance schema is missing; review the target database first.';
    END IF;
    IF to_regclass('identity.users') IS NULL THEN
        RAISE EXCEPTION 'The identity.users table is missing; review the target database first.';
    END IF;
    IF to_regclass('attendance.notice_templates') IS NOT NULL THEN
        RAISE EXCEPTION 'The notice_templates table already exists; review its schema first.';
    END IF;
END $$;

CREATE TABLE attendance.notice_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(200) NOT NULL,
    module varchar(40) NOT NULL,
    sanitized_html text NOT NULL,
    is_active boolean NOT NULL DEFAULT false,
    created_by uuid NOT NULL REFERENCES identity.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_notice_templates_module CHECK (module IN ('TARDINESS', 'RETURN_TO_WORK'))
);

CREATE UNIQUE INDEX uq_notice_templates_active_module
    ON attendance.notice_templates (module) WHERE is_active;
COMMIT;
