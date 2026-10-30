-- Existing installations without an Alembic baseline: apply once instead of the
-- equivalent Alembic revision c8f9012d3e45. Back up the database first.
BEGIN;

CREATE TABLE core.operational_groups (
    company_id uuid NOT NULL REFERENCES core.companies(id) ON DELETE CASCADE,
    operational_group varchar(30) NOT NULL,
    display_name varchar(50) NOT NULL,
    sort_order integer NOT NULL DEFAULT 0,
    is_active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (company_id, operational_group),
    CONSTRAINT ck_operational_groups_code CHECK (operational_group ~ '^[A-Z0-9_-]+$'),
    CONSTRAINT ck_operational_groups_display_name CHECK (length(btrim(display_name)) > 0),
    CONSTRAINT ck_operational_groups_sort_order CHECK (sort_order >= 0)
);

INSERT INTO core.operational_groups
    (company_id, operational_group, display_name, sort_order, is_active)
SELECT c.id, g.code, g.code, g.sort_order, true
FROM core.companies c
CROSS JOIN (VALUES
    ('SLI', 0), ('SLR', 1), ('ASS', 2), ('MTT', 3), ('COLLECTION', 4),
    ('FLEET', 5), ('WAREHOUSE', 6), ('OFFICE', 7), ('OTHER', 8)
) AS g(code, sort_order);

INSERT INTO core.operational_groups
    (company_id, operational_group, display_name, sort_order, is_active)
SELECT DISTINCT company_id, operational_group, operational_group, 9, true
FROM hr.employment_assignments
WHERE operational_group IS NOT NULL
ON CONFLICT (company_id, operational_group) DO NOTHING;

ALTER TABLE hr.employment_assignments
    DROP CONSTRAINT IF EXISTS ck_employment_assignments_operational_group;
ALTER TABLE hr.employment_assignments
    ADD CONSTRAINT fk_assignment_operational_group
    FOREIGN KEY (company_id, operational_group)
    REFERENCES core.operational_groups(company_id, operational_group);

COMMIT;
