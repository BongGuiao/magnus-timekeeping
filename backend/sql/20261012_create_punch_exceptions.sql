BEGIN;

CREATE TABLE IF NOT EXISTS attendance.punch_exceptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempted_at timestamptz NOT NULL,
    requested_user_id uuid NOT NULL,
    attendance_record_id uuid REFERENCES attendance.attendance_records(id) ON DELETE SET NULL,
    punch_action varchar(40) NOT NULL,
    rule_code varchar(60) NOT NULL,
    reason text NOT NULL,
    validation_context jsonb NOT NULL,
    identity_verified boolean,
    client_channel varchar(20) NOT NULL,
    punch_metadata jsonb NOT NULL,
    review_status varchar(20) NOT NULL DEFAULT 'OPEN',
    reviewed_by uuid REFERENCES identity.users(id) ON DELETE SET NULL,
    reviewed_at timestamptz,
    review_notes text,
    CONSTRAINT ck_punch_exceptions_review_status
        CHECK (review_status IN ('OPEN', 'REVIEWED', 'DISMISSED'))
);

CREATE INDEX IF NOT EXISTS ix_punch_exceptions_requested_user_id
    ON attendance.punch_exceptions (requested_user_id);
CREATE INDEX IF NOT EXISTS ix_punch_exceptions_attempted_at
    ON attendance.punch_exceptions (attempted_at DESC);

COMMIT;
