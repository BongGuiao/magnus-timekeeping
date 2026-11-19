BEGIN;

ALTER TABLE core.holidays
    ADD COLUMN IF NOT EXISTS included_municipalities jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS excluded_municipalities jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_holidays_included_municipalities_array'
          AND conrelid = 'core.holidays'::regclass
    ) THEN
        ALTER TABLE core.holidays
            ADD CONSTRAINT ck_holidays_included_municipalities_array
            CHECK (jsonb_typeof(included_municipalities) = 'array');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_holidays_excluded_municipalities_array'
          AND conrelid = 'core.holidays'::regclass
    ) THEN
        ALTER TABLE core.holidays
            ADD CONSTRAINT ck_holidays_excluded_municipalities_array
            CHECK (jsonb_typeof(excluded_municipalities) = 'array');
    END IF;
END
$$;

DROP INDEX IF EXISTS core.uq_holidays_calendar_date_name_scope;

CREATE UNIQUE INDEX uq_holidays_calendar_date_name_scope
    ON core.holidays (
        holiday_calendar_id,
        holiday_date,
        holiday_name,
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_region_code, upper(btrim(region)), '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_province_code, upper(btrim(province)), '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_city_code, upper(btrim(city)), '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(ncr_district, '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN md5(included_municipalities::text) ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN md5(excluded_municipalities::text) ELSE '' END)
    );

COMMIT;
