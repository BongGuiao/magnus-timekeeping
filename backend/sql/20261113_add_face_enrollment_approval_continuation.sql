BEGIN;

-- NULL means direct HR approval; otherwise this snapshots the original approval ID.
ALTER TABLE biometric.face_enrollment_similarity_overrides
    ADD COLUMN IF NOT EXISTS source_override_id uuid;

COMMIT;
