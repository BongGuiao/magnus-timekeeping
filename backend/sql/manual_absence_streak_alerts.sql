-- For an existing untracked database only. Back up and review the schema first.
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
    IF to_regclass('attendance.attendance_records') IS NULL
       OR to_regclass('hr.employees') IS NULL
       OR to_regclass('identity.users') IS NULL
       OR to_regclass('core.companies') IS NULL THEN
        RAISE EXCEPTION 'Required attendance, employee, user, or company table is missing.';
    END IF;
    IF to_regclass('attendance.absence_streak_alerts') IS NOT NULL
       OR to_regclass('attendance.absence_streak_dismissals') IS NOT NULL
       OR to_regclass('attendance.ix_attendance_valid_absence_user_date') IS NOT NULL THEN
        RAISE EXCEPTION 'An absence alert table or index already exists; review the schema first.';
    END IF;
END $$;

CREATE TABLE attendance.absence_streak_alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    company_id uuid NOT NULL REFERENCES core.companies(id),
    first_absence_date date NOT NULL,
    second_absence_date date NOT NULL,
    third_absence_date date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CONSTRAINT uq_absence_streak_employee_start UNIQUE (employee_id, first_absence_date)
);
CREATE TABLE attendance.absence_streak_dismissals (
    alert_id uuid NOT NULL REFERENCES attendance.absence_streak_alerts(id),
    user_id uuid NOT NULL REFERENCES identity.users(id),
    dismissed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (alert_id, user_id)
);
CREATE INDEX ix_attendance_valid_absence_user_date
    ON attendance.attendance_records (user_id, work_date)
    WHERE is_absent AND record_status = 'VALID';
COMMIT;
