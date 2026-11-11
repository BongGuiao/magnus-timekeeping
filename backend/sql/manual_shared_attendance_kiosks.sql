-- Mirrors c9d0e1f2a3b4 only, for an existing manually maintained database.
-- Back up first. Do not apply this to an Alembic-managed installation.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    tracked boolean;
BEGIN
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.alembic_version)' INTO tracked;
        IF tracked THEN
            RAISE EXCEPTION 'Use Alembic for this tracked database, not the manual kiosk script.';
        END IF;
    END IF;
    IF to_regclass('identity.kiosk_devices') IS NOT NULL
        OR to_regclass('identity.kiosk_challenges') IS NOT NULL THEN
        RAISE EXCEPTION 'Kiosk tables already exist or are partially installed; review the schema first.';
    END IF;
    IF to_regclass('core.companies') IS NULL OR to_regclass('core.locations') IS NULL
        OR to_regclass('identity.users') IS NULL OR to_regclass('hr.employment_assignments') IS NULL
        OR to_regclass('hr.employment_assignment_locations') IS NULL THEN
        RAISE EXCEPTION 'Required existing company, location, account or assignment tables are missing.';
    END IF;
END $$;

CREATE TABLE identity.kiosk_devices (
    id uuid PRIMARY KEY,
    device_name varchar(100) NOT NULL,
    public_key_jwk jsonb NOT NULL,
    status varchar(20) NOT NULL,
    pairing_code varchar(32) NOT NULL UNIQUE,
    pairing_expires_at timestamptz NOT NULL,
    company_id uuid REFERENCES core.companies(id),
    location_id uuid,
    approved_by uuid,
    approved_at timestamptz,
    revoked_by uuid,
    revoked_at timestamptz,
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_kiosk_status CHECK (status IN ('PENDING', 'APPROVED', 'REVOKED')),
    CONSTRAINT ck_kiosk_approved_scope CHECK (
        status != 'APPROVED' OR (company_id IS NOT NULL AND location_id IS NOT NULL)
    ),
    CONSTRAINT fk_kiosk_location_company FOREIGN KEY (company_id, location_id)
        REFERENCES core.locations(company_id, id)
);

CREATE TABLE identity.kiosk_challenges (
    id uuid PRIMARY KEY,
    device_id uuid NOT NULL REFERENCES identity.kiosk_devices(id) ON DELETE CASCADE,
    purpose varchar(10) NOT NULL,
    payload_hash varchar(64) NOT NULL,
    message varchar(500) NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    CONSTRAINT ck_kiosk_challenge_purpose CHECK (purpose IN ('STATUS', 'IDENTIFY', 'CLOCK', 'BREAK'))
);
CREATE INDEX ix_identity_kiosk_challenges_device_id ON identity.kiosk_challenges(device_id);
CREATE INDEX ix_identity_kiosk_challenges_expires_at ON identity.kiosk_challenges(expires_at);

COMMIT;
