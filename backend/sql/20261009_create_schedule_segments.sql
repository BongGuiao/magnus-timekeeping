BEGIN;

CREATE TABLE IF NOT EXISTS schedule.schedule_segments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_template_id uuid NOT NULL
        REFERENCES schedule.schedule_templates(id) ON DELETE CASCADE,
    segment_sequence smallint NOT NULL,
    segment_type varchar(30) NOT NULL,
    start_time time NOT NULL,
    end_time time NOT NULL,
    end_day_offset smallint NOT NULL DEFAULT 0,
    paid_minutes core.positive_minutes NOT NULL DEFAULT 0,
    punch_required boolean NOT NULL DEFAULT false,
    auto_deduct boolean NOT NULL DEFAULT false,
    flex_start_minutes core.positive_minutes NOT NULL DEFAULT 0,
    CONSTRAINT ck_schedule_segments_segment_type CHECK (
        segment_type IN ('WORK', 'PAID_BREAK', 'UNPAID_BREAK')
    ),
    CONSTRAINT ck_schedule_segments_end_day_offset CHECK (
        end_day_offset BETWEEN 0 AND 2
    ),
    CONSTRAINT uq_schedule_segments_template_sequence UNIQUE (
        schedule_template_id,
        segment_sequence
    )
);

COMMIT;
