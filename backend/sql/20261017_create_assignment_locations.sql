BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_locations_company_id_id'
          AND conrelid = 'core.locations'::regclass
    ) THEN
        ALTER TABLE core.locations
            ADD CONSTRAINT uq_locations_company_id_id UNIQUE (company_id, id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS hr.employment_assignment_locations (
    assignment_id uuid NOT NULL,
    company_id uuid NOT NULL,
    location_id uuid NOT NULL,
    PRIMARY KEY (assignment_id, location_id),
    CONSTRAINT fk_assignment_locations_assignment_company
        FOREIGN KEY (assignment_id, company_id)
        REFERENCES hr.employment_assignments (id, company_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_assignment_locations_company_location
        FOREIGN KEY (company_id, location_id)
        REFERENCES core.locations (company_id, id)
        ON DELETE CASCADE
);

INSERT INTO hr.employment_assignment_locations (assignment_id, company_id, location_id)
SELECT assignment.id, assignment.company_id, assignment.primary_location_id
FROM hr.employment_assignments AS assignment
JOIN core.locations AS location
  ON location.id = assignment.primary_location_id
 AND location.company_id = assignment.company_id
WHERE assignment.primary_location_id IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO hr.employment_assignment_locations (assignment_id, company_id, location_id)
SELECT DISTINCT assignment.id, assignment.company_id, geofence.location_id
FROM hr.employment_assignments AS assignment
JOIN hr.employment_assignment_geofences AS assignment_geofence
  ON assignment_geofence.assignment_id = assignment.id
 AND assignment_geofence.company_id = assignment.company_id
JOIN location.geofences AS geofence
  ON geofence.id = assignment_geofence.geofence_id
 AND geofence.company_id = assignment.company_id
JOIN core.locations AS location
  ON location.id = geofence.location_id
 AND location.company_id = assignment.company_id
WHERE geofence.location_id IS NOT NULL
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_assignment_locations_company_location
    ON hr.employment_assignment_locations (company_id, location_id);

COMMIT;
