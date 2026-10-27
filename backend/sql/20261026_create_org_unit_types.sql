BEGIN;

CREATE TABLE IF NOT EXISTS core.org_unit_types (
    company_id uuid NOT NULL
        REFERENCES core.companies(id) ON DELETE CASCADE,
    org_unit_type varchar(30) NOT NULL,
    display_name varchar(50) NOT NULL,
    sort_order integer NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT pk_org_unit_types PRIMARY KEY (company_id, org_unit_type),
    CONSTRAINT ck_org_unit_types_code_not_empty
        CHECK (length(btrim(org_unit_type)) > 0),
    CONSTRAINT ck_org_unit_types_display_name_not_empty
        CHECK (length(btrim(display_name)) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_org_unit_types_single_default_per_company
    ON core.org_unit_types (company_id)
    WHERE is_default;

INSERT INTO core.org_unit_types (
    company_id,
    org_unit_type,
    display_name,
    sort_order,
    is_default,
    is_active
)
SELECT
    company.id,
    type.org_unit_type,
    type.display_name,
    type.sort_order,
    type.is_default,
    true
FROM core.companies AS company
CROSS JOIN (
    VALUES
        ('DIVISION', 'Division', 10, false),
        ('DEPARTMENT', 'Department', 20, true),
        ('TEAM', 'Team', 30, false),
        ('BRANCH', 'Branch', 40, false),
        ('COST_CENTER', 'Cost center', 50, false)
) AS type(org_unit_type, display_name, sort_order, is_default)
ON CONFLICT (company_id, org_unit_type) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    sort_order = EXCLUDED.sort_order,
    is_default = EXCLUDED.is_default,
    is_active = EXCLUDED.is_active;

COMMIT;
