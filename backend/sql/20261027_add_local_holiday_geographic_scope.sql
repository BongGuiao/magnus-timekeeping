BEGIN;

ALTER TABLE core.holidays
    ADD COLUMN IF NOT EXISTS region varchar(100),
    ADD COLUMN IF NOT EXISTS province varchar(100),
    ADD COLUMN IF NOT EXISTS city varchar(100),
    ADD COLUMN IF NOT EXISTS psgc_region_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_province_code varchar(9),
    ADD COLUMN IF NOT EXISTS psgc_city_code varchar(9),
    ADD COLUMN IF NOT EXISTS ncr_district varchar(30);

ALTER TABLE core.locations
    ADD COLUMN IF NOT EXISTS ncr_district varchar(30);

DO $$
BEGIN
    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'holiday_calendars'
          AND column_name IN (
              'region',
              'province',
              'city',
              'psgc_region_code',
              'psgc_province_code',
              'psgc_city_code'
          )
    ) = 6 THEN
        UPDATE core.holidays AS holiday
        SET region = COALESCE(holiday.region, calendar.region),
            province = COALESCE(holiday.province, calendar.province),
            city = COALESCE(holiday.city, calendar.city),
            psgc_region_code = COALESCE(holiday.psgc_region_code, calendar.psgc_region_code),
            psgc_province_code = COALESCE(holiday.psgc_province_code, calendar.psgc_province_code),
            psgc_city_code = COALESCE(holiday.psgc_city_code, calendar.psgc_city_code)
        FROM core.holiday_calendars AS calendar
        WHERE holiday.holiday_calendar_id = calendar.id
          AND holiday.holiday_type = 'LOCAL';
    END IF;

END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_holidays_psgc_codes'
          AND conrelid = 'core.holidays'::regclass
    ) THEN
        ALTER TABLE core.holidays
            ADD CONSTRAINT ck_holidays_psgc_codes CHECK (
                (psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$')
                AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$')
                AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$')
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_holidays_ncr_district'
          AND conrelid = 'core.holidays'::regclass
    ) THEN
        ALTER TABLE core.holidays
            ADD CONSTRAINT ck_holidays_ncr_district CHECK (
                ncr_district IS NULL OR ncr_district IN (
                    'NCR_1ST_DISTRICT',
                    'NCR_2ND_DISTRICT',
                    'NCR_3RD_DISTRICT',
                    'NCR_4TH_DISTRICT'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_locations_ncr_district'
          AND conrelid = 'core.locations'::regclass
    ) THEN
        ALTER TABLE core.locations
            ADD CONSTRAINT chk_locations_ncr_district CHECK (
                ncr_district IS NULL OR ncr_district IN (
                    'NCR_1ST_DISTRICT',
                    'NCR_2ND_DISTRICT',
                    'NCR_3RD_DISTRICT',
                    'NCR_4TH_DISTRICT'
                )
            );
    END IF;
END
$$;

ALTER TABLE core.holiday_calendars
    DROP CONSTRAINT IF EXISTS ck_holiday_calendars_psgc_codes,
    DROP COLUMN IF EXISTS region,
    DROP COLUMN IF EXISTS province,
    DROP COLUMN IF EXISTS city,
    DROP COLUMN IF EXISTS psgc_region_code,
    DROP COLUMN IF EXISTS psgc_province_code,
    DROP COLUMN IF EXISTS psgc_city_code;

ALTER TABLE core.holidays
    DROP CONSTRAINT IF EXISTS uq_holidays_calendar_date_name;

DROP INDEX IF EXISTS core.uq_holidays_calendar_date_name_scope;

CREATE UNIQUE INDEX uq_holidays_calendar_date_name_scope
    ON core.holidays (
        holiday_calendar_id,
        holiday_date,
        holiday_name,
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_region_code, upper(btrim(region)), '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_province_code, upper(btrim(province)), '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_city_code, upper(btrim(city)), '') ELSE '' END),
        (CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(ncr_district, '') ELSE '' END)
    );

COMMIT;
