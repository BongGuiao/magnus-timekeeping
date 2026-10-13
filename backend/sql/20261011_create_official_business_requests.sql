BEGIN;

CREATE TABLE IF NOT EXISTS attendance.official_business_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_no varchar(50) NOT NULL UNIQUE,
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    destination varchar(300) NOT NULL,
    purpose text NOT NULL,
    client_name varchar(200),
    geofence_id uuid REFERENCES location.geofences(id),
    jo_reference varchar(100),
    vehicle_id uuid,
    requested_minutes core.positive_minutes NOT NULL,
    approved_minutes core.positive_minutes,
    workflow_instance_id uuid REFERENCES workflow.instances(id),
    status varchar(30) NOT NULL DEFAULT 'DRAFT',
    payroll_posted boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid,
    row_version integer NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true,
    CHECK (end_at > start_at)
);

DO $$
BEGIN
    IF to_regclass('fleet.vehicles') IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'attendance.official_business_requests'::regclass
              AND contype = 'f'
              AND conkey = ARRAY[(
                  SELECT attnum FROM pg_attribute
                  WHERE attrelid = 'attendance.official_business_requests'::regclass
                    AND attname = 'vehicle_id'
              )]
        ) THEN
        ALTER TABLE attendance.official_business_requests
            ADD CONSTRAINT fk_ob_vehicle FOREIGN KEY (vehicle_id) REFERENCES fleet.vehicles(id);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_official_business_requests_employee
    ON attendance.official_business_requests (employee_id, start_at DESC);

CREATE INDEX IF NOT EXISTS ix_official_business_requests_pending
    ON attendance.official_business_requests (status, created_at)
    WHERE is_active = true;

COMMIT;
