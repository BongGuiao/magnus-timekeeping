CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.announcements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NULL REFERENCES core.companies(id) ON DELETE CASCADE,
    title varchar(200) NOT NULL,
    body text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    effective_from date NOT NULL DEFAULT CURRENT_DATE,
    effective_to date NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid NOT NULL,
    row_version integer NOT NULL DEFAULT 1,
    CONSTRAINT ck_announcements_effective_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS ix_announcements_active_created_at
    ON core.announcements (is_active, created_at DESC);
