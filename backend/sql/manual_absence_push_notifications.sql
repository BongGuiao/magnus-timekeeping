-- For an existing untracked database after the absence-alert schema is installed.
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
    IF to_regclass('attendance.absence_streak_alerts') IS NULL
       OR to_regclass('identity.users') IS NULL THEN
        RAISE EXCEPTION 'Required absence alert or user table is missing.';
    END IF;
    IF to_regclass('identity.mobile_push_devices') IS NOT NULL
       OR to_regclass('attendance.absence_push_deliveries') IS NOT NULL
       OR to_regclass('attendance.ix_absence_push_due') IS NOT NULL THEN
        RAISE EXCEPTION 'A push table or index already exists; review the schema first.';
    END IF;
END $$;

CREATE TABLE identity.mobile_push_devices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES identity.users(id),
    token varchar(255) NOT NULL UNIQUE,
    session_expires_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE attendance.absence_push_deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id uuid NOT NULL REFERENCES attendance.absence_streak_alerts(id),
    user_id uuid NOT NULL REFERENCES identity.users(id),
    device_id uuid NOT NULL REFERENCES identity.mobile_push_devices(id),
    state varchar(16) NOT NULL DEFAULT 'PENDING',
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    receipt_id varchar(255),
    sent_at timestamptz,
    CONSTRAINT uq_absence_push_recipient_device UNIQUE (alert_id, user_id, device_id)
);
CREATE INDEX ix_absence_push_due
    ON attendance.absence_push_deliveries (state, next_attempt_at);
COMMIT;
