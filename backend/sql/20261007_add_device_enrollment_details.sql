BEGIN;

ALTER TABLE identity.devices
    ADD COLUMN IF NOT EXISTS device_name varchar(100),
    ADD COLUMN IF NOT EXISTS enrollment_ip varchar(45);

COMMIT;
