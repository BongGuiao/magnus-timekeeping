BEGIN;

CREATE TABLE IF NOT EXISTS identity.device_credentials (
    device_id uuid PRIMARY KEY REFERENCES identity.devices(id) ON DELETE CASCADE,
    public_key_jwk jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS identity.device_challenges (
    id uuid PRIMARY KEY,
    device_id uuid NOT NULL REFERENCES identity.devices(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
    action varchar(10) NOT NULL CHECK (action IN ('CLOCK', 'BREAK')),
    nonce varchar(64) NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_device_challenges_expires_at
    ON identity.device_challenges (expires_at);

COMMIT;
