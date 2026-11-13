BEGIN;

-- Identifiers are snapshots, not cascading foreign keys, so audit history survives deletion.
CREATE TABLE IF NOT EXISTS biometric.face_enrollment_resets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL,
    employee_no varchar(30) NOT NULL,
    reset_by uuid NOT NULL,
    reset_at timestamptz NOT NULL DEFAULT now(),
    sample_ids uuid[] NOT NULL,
    sample_count integer NOT NULL,
    reason varchar(500) NOT NULL,
    profile_photo_cleared boolean NOT NULL DEFAULT false,
    CONSTRAINT ck_face_enrollment_resets_samples
        CHECK (sample_count > 0 AND cardinality(sample_ids) = sample_count),
    CONSTRAINT ck_face_enrollment_resets_reason CHECK (length(btrim(reason)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_face_enrollment_resets_employee_time
    ON biometric.face_enrollment_resets (employee_id, reset_at);

COMMIT;
