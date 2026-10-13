BEGIN;

ALTER TABLE core.companies
    ADD COLUMN IF NOT EXISTS region varchar(100),
    ADD COLUMN IF NOT EXISTS psgc_region_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_province_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_city_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_barangay_code varchar(9);

ALTER TABLE core.locations
    ADD COLUMN IF NOT EXISTS region varchar(100),
    ADD COLUMN IF NOT EXISTS psgc_region_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_province_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_city_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_barangay_code varchar(9);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_companies_psgc_codes'
          AND conrelid = 'core.companies'::regclass
    ) THEN
        ALTER TABLE core.companies
            ADD CONSTRAINT chk_companies_psgc_codes CHECK (
                (psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$')
                AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$')
                AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$')
                AND (psgc_barangay_code IS NULL OR psgc_barangay_code ~ '^[0-9]{9}$')
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_locations_psgc_codes'
          AND conrelid = 'core.locations'::regclass
    ) THEN
        ALTER TABLE core.locations
            ADD CONSTRAINT chk_locations_psgc_codes CHECK (
                (psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$')
                AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$')
                AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$')
                AND (psgc_barangay_code IS NULL OR psgc_barangay_code ~ '^[0-9]{9}$')
            );
    END IF;
END
$$;

COMMIT;
