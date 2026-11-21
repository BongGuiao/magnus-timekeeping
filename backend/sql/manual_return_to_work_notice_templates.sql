-- For an existing untracked database where notice_templates was created manually.
-- Back up and review the schema first. Use Alembic instead for tracked databases.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    tracked boolean;
    constraint_definition text;
BEGIN
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.alembic_version)' INTO tracked;
        IF tracked THEN
            RAISE EXCEPTION 'Use Alembic for this tracked database, not the manual script.';
        END IF;
    END IF;
    IF to_regclass('attendance.notice_templates') IS NULL THEN
        RAISE EXCEPTION 'The notice_templates table is missing; review the schema first.';
    END IF;
    SELECT pg_get_constraintdef(oid) INTO constraint_definition
    FROM pg_constraint
    WHERE conrelid = to_regclass('attendance.notice_templates')
      AND conname = 'ck_notice_templates_module'
      AND contype = 'c';
    IF constraint_definition IS DISTINCT FROM $expected$CHECK (((module)::text = 'TARDINESS'::text))$expected$ THEN
        RAISE EXCEPTION 'The module constraint is missing, different, or already updated; review the schema first.';
    END IF;
END $$;

ALTER TABLE attendance.notice_templates DROP CONSTRAINT ck_notice_templates_module;
ALTER TABLE attendance.notice_templates ADD CONSTRAINT ck_notice_templates_module
    CHECK (module IN ('TARDINESS', 'RETURN_TO_WORK'));
COMMIT;
