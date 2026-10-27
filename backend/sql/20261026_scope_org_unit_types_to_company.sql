BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'org_unit_types'
          AND column_name = 'company_id'
    ) THEN
        IF NOT EXISTS (SELECT 1 FROM core.companies LIMIT 1) THEN
            RAISE EXCEPTION 'Cannot scope organization unit types: core.companies has no rows.';
        END IF;

        CREATE TEMP TABLE org_unit_types_before_company_scope
        ON COMMIT DROP
        AS
        SELECT org_unit_type, display_name, sort_order, is_default, is_active
        FROM core.org_unit_types;

        DROP INDEX IF EXISTS core.uq_org_unit_types_single_default;

        ALTER TABLE core.org_unit_types
            DROP CONSTRAINT IF EXISTS org_unit_types_pkey,
            DROP CONSTRAINT IF EXISTS pk_org_unit_types;

        ALTER TABLE core.org_unit_types
            ADD COLUMN company_id uuid;

        DELETE FROM core.org_unit_types;

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
            previous.org_unit_type,
            previous.display_name,
            previous.sort_order,
            previous.is_default,
            previous.is_active
        FROM core.companies AS company
        CROSS JOIN org_unit_types_before_company_scope AS previous;

        ALTER TABLE core.org_unit_types
            ALTER COLUMN company_id SET NOT NULL,
            ADD CONSTRAINT pk_org_unit_types PRIMARY KEY (company_id, org_unit_type),
            ADD CONSTRAINT fk_org_unit_types_company
                FOREIGN KEY (company_id)
                REFERENCES core.companies(id)
                ON DELETE CASCADE;
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_org_unit_types_single_default_per_company
    ON core.org_unit_types (company_id)
    WHERE is_default;

COMMIT;
