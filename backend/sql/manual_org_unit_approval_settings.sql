-- Mirrors Alembic revision b8c0d2e4f6a8 for manually maintained databases.
BEGIN;

ALTER TABLE core.org_units
    ADD COLUMN manager_is_approver boolean NOT NULL DEFAULT true,
    ADD COLUMN excluded_approval_org_unit_ids uuid[] NOT NULL DEFAULT '{}'::uuid[];

COMMIT;
