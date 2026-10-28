BEGIN;

-- Locations and geofences are soft-deleted so attendance logs, official business requests,
-- WFH records, and assignment history that reference them remain intact and readable.
ALTER TABLE core.locations
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_by uuid REFERENCES identity.users(id);

ALTER TABLE location.geofences
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_by uuid REFERENCES identity.users(id);

CREATE INDEX IF NOT EXISTS ix_locations_company_not_deleted
    ON core.locations (company_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_geofences_company_not_deleted
    ON location.geofences (company_id)
    WHERE deleted_at IS NULL;

COMMIT;
