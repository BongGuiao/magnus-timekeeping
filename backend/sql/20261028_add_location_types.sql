BEGIN;

CREATE TABLE IF NOT EXISTS core.location_types (
    company_id uuid NOT NULL
        REFERENCES core.companies(id) ON DELETE CASCADE,
    location_type varchar(30) NOT NULL,
    display_name varchar(50) NOT NULL,
    sort_order integer NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT pk_location_types PRIMARY KEY (company_id, location_type),
    CONSTRAINT ck_location_types_code_not_empty
        CHECK (length(btrim(location_type)) > 0),
    CONSTRAINT ck_location_types_display_name_not_empty
        CHECK (length(btrim(display_name)) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_location_types_single_default_per_company
    ON core.location_types (company_id)
    WHERE is_default;

INSERT INTO core.location_types (
    company_id,
    location_type,
    display_name,
    sort_order,
    is_default,
    is_active
)
SELECT
    company.id,
    type.location_type,
    type.display_name,
    type.sort_order,
    type.is_default,
    true
FROM core.companies AS company
CROSS JOIN (
    VALUES
        ('OFFICE', 'Office', 10, true),
        ('WAREHOUSE', 'Warehouse', 20, false),
        ('DISPATCH', 'Dispatch', 30, false),
        ('CUSTOMER', 'Customer', 40, false),
        ('FIELD', 'Field', 50, false),
        ('FLEET_YARD', 'Fleet yard', 60, false),
        ('OTHER', 'Other', 70, false)
) AS type(location_type, display_name, sort_order, is_default)
ON CONFLICT (company_id, location_type) DO NOTHING;

ALTER TABLE core.locations
    DROP CONSTRAINT IF EXISTS chk_locations_type_valid,
    DROP CONSTRAINT IF EXISTS locations_location_type_check,
    DROP CONSTRAINT IF EXISTS fk_locations_location_type;

ALTER TABLE core.locations
    ADD CONSTRAINT fk_locations_location_type
    FOREIGN KEY (company_id, location_type)
    REFERENCES core.location_types (company_id, location_type)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT;

COMMIT;
