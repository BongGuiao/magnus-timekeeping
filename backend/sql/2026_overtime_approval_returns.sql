CREATE TABLE IF NOT EXISTS attendance.overtime_approval_returns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL REFERENCES attendance.overtime_applications(id),
    actor_id uuid NOT NULL,
    reason text NOT NULL CONSTRAINT ck_overtime_approval_returns_reason CHECK (length(trim(reason)) > 0),
    previous_approved_minutes integer,
    previous_payable_minutes integer,
    returned_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_overtime_approval_returns_application_id
    ON attendance.overtime_approval_returns (application_id);
