BEGIN;

CREATE TABLE IF NOT EXISTS attendance.offline_permits (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES identity.users(id),
    device_id uuid NOT NULL REFERENCES identity.devices(id),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    snapshot jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attendance_offline_permits_user_id
    ON attendance.offline_permits(user_id);

CREATE TABLE IF NOT EXISTS attendance.offline_punch_events (
    id uuid PRIMARY KEY,
    permit_id uuid NOT NULL REFERENCES attendance.offline_permits(id),
    user_id uuid NOT NULL REFERENCES identity.users(id),
    sequence integer NOT NULL,
    captured_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    payload_hash varchar(64) NOT NULL,
    payload jsonb NOT NULL,
    signature varchar(86) NOT NULL,
    status varchar(20) NOT NULL,
    reason text,
    attendance_id uuid REFERENCES attendance.attendance_records(id),
    encrypted_photo bytea,
    reviewed_at timestamptz,
    reviewed_by uuid REFERENCES identity.users(id),
    review_notes text,
    CONSTRAINT uq_offline_event_sequence UNIQUE (permit_id, sequence),
    CONSTRAINT ck_offline_event_status CHECK (status IN ('ACCEPTED', 'NEEDS_REVIEW', 'REJECTED'))
);
CREATE INDEX IF NOT EXISTS ix_attendance_offline_punch_events_user_id
    ON attendance.offline_punch_events(user_id);
CREATE INDEX IF NOT EXISTS ix_attendance_offline_punch_events_status
    ON attendance.offline_punch_events(status);

COMMIT;
