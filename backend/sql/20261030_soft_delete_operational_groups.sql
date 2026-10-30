-- Apply once after 20261030_create_operational_groups.sql.
-- Use this OR Alembic revision d9a0123e4f56, not both.
BEGIN;

ALTER TABLE core.operational_groups
    ADD COLUMN deleted_at timestamptz,
    ADD COLUMN deleted_by uuid,
    ADD CONSTRAINT fk_operational_groups_deleted_by
        FOREIGN KEY (deleted_by) REFERENCES identity.users(id);

COMMIT;
