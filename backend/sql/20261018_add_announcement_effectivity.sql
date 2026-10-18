ALTER TABLE core.announcements
    ADD COLUMN IF NOT EXISTS effective_from date;

ALTER TABLE core.announcements
    ADD COLUMN IF NOT EXISTS effective_to date;

UPDATE core.announcements
SET effective_from = created_at::date
WHERE effective_from IS NULL;

ALTER TABLE core.announcements
    ALTER COLUMN effective_from SET DEFAULT CURRENT_DATE,
    ALTER COLUMN effective_from SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_announcements_effective_dates'
          AND conrelid = 'core.announcements'::regclass
    ) THEN
        ALTER TABLE core.announcements
            ADD CONSTRAINT ck_announcements_effective_dates
            CHECK (effective_to IS NULL OR effective_to >= effective_from);
    END IF;
END;
$$;
