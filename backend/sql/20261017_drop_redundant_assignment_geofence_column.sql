BEGIN;

ALTER TABLE hr.employment_assignments
    DROP COLUMN IF EXISTS authorized_geofence_id;

COMMIT;
