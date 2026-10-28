BEGIN;

ALTER TABLE core.location_types
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_by uuid REFERENCES identity.users(id);

ALTER TABLE core.org_units
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_by uuid REFERENCES identity.users(id);

ALTER TABLE core.org_unit_types
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_by uuid REFERENCES identity.users(id);

ALTER TABLE core.org_units
    DROP CONSTRAINT IF EXISTS ck_org_units_status,
    DROP CONSTRAINT IF EXISTS org_units_status_check;

ALTER TABLE core.org_units
    ADD CONSTRAINT ck_org_units_status
    CHECK (status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'DELETED'));

CREATE INDEX IF NOT EXISTS ix_location_types_company_not_deleted
    ON core.location_types (company_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_org_units_company_not_deleted
    ON core.org_units (company_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_org_unit_types_company_not_deleted
    ON core.org_unit_types (company_id)
    WHERE deleted_at IS NULL;

COMMIT;
