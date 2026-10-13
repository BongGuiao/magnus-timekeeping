BEGIN;

ALTER TABLE schedule.schedule_segments
    ADD COLUMN IF NOT EXISTS break_slot varchar(30),
    ADD COLUMN IF NOT EXISTS work_segment_sequence smallint,
    ADD COLUMN IF NOT EXISTS break_minutes integer NOT NULL DEFAULT 0;

DO $$
BEGIN
IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'schedule.schedule_segments'::regclass
      AND conname = 'ck_schedule_segments_break_rule'
) THEN
ALTER TABLE schedule.schedule_segments ADD CONSTRAINT ck_schedule_segments_break_rule CHECK (
        (break_slot IS NULL AND work_segment_sequence IS NULL AND break_minutes = 0)
        OR (
            break_slot IS NOT NULL
            AND segment_type IN ('PAID_BREAK', 'UNPAID_BREAK')
            AND break_slot IN ('FIRST_BREAK', 'MEAL_BREAK', 'SECOND_BREAK')
            AND work_segment_sequence IS NOT NULL AND break_minutes > 0
        )
    );
END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_segments_break_slot
    ON schedule.schedule_segments (schedule_template_id, break_slot)
    WHERE break_slot IS NOT NULL;

COMMIT;
