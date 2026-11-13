BEGIN;

-- Identifiers are snapshots, not cascading foreign keys, so approval history survives resets and deletion.
CREATE TABLE IF NOT EXISTS biometric.face_enrollment_similarity_overrides (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id uuid NOT NULL,
    employee_id uuid NOT NULL,
    employee_no varchar(30) NOT NULL,
    conflicting_employee_ids uuid[] NOT NULL,
    conflicting_employee_nos varchar(30)[] NOT NULL,
    closest_distance double precision NOT NULL,
    threshold double precision NOT NULL,
    reason varchar(500) NOT NULL,
    approved_by uuid NOT NULL,
    approved_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_face_enrollment_overrides_conflicts CHECK (
        cardinality(conflicting_employee_ids) > 0
        AND cardinality(conflicting_employee_ids) = cardinality(conflicting_employee_nos)
    ),
    CONSTRAINT ck_face_enrollment_overrides_reason CHECK (length(btrim(reason)) > 0)
);

CREATE INDEX IF NOT EXISTS ix_face_enrollment_overrides_employee_time
    ON biometric.face_enrollment_similarity_overrides (employee_id, approved_at);

COMMIT;
