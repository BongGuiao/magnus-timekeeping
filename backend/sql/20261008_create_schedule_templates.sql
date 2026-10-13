BEGIN;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS schedule;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type AS t
        JOIN pg_namespace AS ns ON ns.oid = t.typnamespace
        WHERE ns.nspname = 'core'
          AND t.typname = 'positive_minutes'
          AND t.typtype = 'd'
    ) THEN
        CREATE DOMAIN core.positive_minutes AS integer
        CHECK (VALUE >= 0);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS schedule.schedule_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES core.companies(id),
    schedule_code varchar(30) NOT NULL,
    schedule_name varchar(150) NOT NULL,
    schedule_type varchar(30) NOT NULL,
    required_minutes core.positive_minutes NOT NULL,
    grace_minutes core.positive_minutes NOT NULL DEFAULT 0,
    grace_method varchar(30) NOT NULL DEFAULT 'NONE',
    is_overnight boolean NOT NULL DEFAULT false,
    ot_eligible boolean NOT NULL DEFAULT true,
    pre_shift_ot_allowed boolean NOT NULL DEFAULT false,
    minimum_ot_minutes core.positive_minutes NOT NULL DEFAULT 0,
    holiday_calendar_id uuid REFERENCES core.holiday_calendars(id),
    effective_from date NOT NULL,
    effective_to date,
    status varchar(20) NOT NULL DEFAULT 'DRAFT',
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid,
    row_version integer NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT ck_schedule_templates_schedule_type CHECK (
        schedule_type IN ('FIXED', 'FLEXIBLE', 'SHIFTING', 'OVERNIGHT', 'SPLIT',
                          'COMPRESSED', 'FIELD', 'ON_CALL')
    ),
    CONSTRAINT uq_schedule_templates_company_code UNIQUE (company_id, schedule_code),
    CONSTRAINT ck_schedule_templates_effective_dates CHECK (
        effective_to IS NULL OR effective_to >= effective_from
    )
);

COMMIT;
