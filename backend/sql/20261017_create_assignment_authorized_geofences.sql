BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_employment_assignments_id_company'
          AND conrelid = 'hr.employment_assignments'::regclass
    ) THEN
        ALTER TABLE hr.employment_assignments
            ADD CONSTRAINT uq_employment_assignments_id_company UNIQUE (id, company_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_geofences_company_id_id'
          AND conrelid = 'location.geofences'::regclass
    ) THEN
        ALTER TABLE location.geofences
            ADD CONSTRAINT uq_geofences_company_id_id UNIQUE (company_id, id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS hr.employment_assignment_geofences (
    assignment_id uuid NOT NULL,
    company_id uuid NOT NULL,
    geofence_id uuid NOT NULL,
    PRIMARY KEY (assignment_id, geofence_id),
    CONSTRAINT fk_assignment_geofences_assignment_company
        FOREIGN KEY (assignment_id, company_id)
        REFERENCES hr.employment_assignments (id, company_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_assignment_geofences_company_geofence
        FOREIGN KEY (company_id, geofence_id)
        REFERENCES location.geofences (company_id, id)
        ON DELETE CASCADE
);

WITH single_geofence_locations AS (
    SELECT company_id, location_id
    FROM location.geofences
    WHERE location_id IS NOT NULL
    GROUP BY company_id, location_id
    HAVING COUNT(*) = 1
)
INSERT INTO hr.employment_assignment_geofences (assignment_id, company_id, geofence_id)
SELECT assignment.id, assignment.company_id, geofence.id
FROM hr.employment_assignments AS assignment
JOIN location.geofences AS geofence
  ON geofence.company_id = assignment.company_id
 AND geofence.location_id = assignment.primary_location_id
JOIN single_geofence_locations AS single_location
  ON single_location.company_id = assignment.company_id
 AND single_location.location_id = assignment.primary_location_id
WHERE assignment.primary_location_id IS NOT NULL
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_assignment_geofences_company_fence
    ON hr.employment_assignment_geofences (company_id, geofence_id);

COMMIT;
