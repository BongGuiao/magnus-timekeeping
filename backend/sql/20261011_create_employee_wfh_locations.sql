BEGIN;

CREATE TABLE IF NOT EXISTS hr.employee_wfh_locations (
    employee_id uuid PRIMARY KEY REFERENCES hr.employees(id) ON DELETE CASCADE,
    geofence_id uuid NOT NULL REFERENCES location.geofences(id),
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL,
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_employee_wfh_latitude CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_employee_wfh_longitude CHECK (longitude BETWEEN -180 AND 180)
);

COMMIT;
