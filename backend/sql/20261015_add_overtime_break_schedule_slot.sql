BEGIN;

UPDATE schedule.schedule_segments
SET segment_type = 'PAID_BREAK',
    auto_deduct = false,
    punch_required = true
WHERE break_slot IN ('FIRST_BREAK', 'SECOND_BREAK', 'OT_BREAK')
  AND (
      segment_type <> 'PAID_BREAK'
      OR auto_deduct
      OR NOT punch_required
  );

ALTER TABLE schedule.schedule_segments
    DROP CONSTRAINT IF EXISTS ck_schedule_segments_break_rule;

ALTER TABLE schedule.schedule_segments
    ADD CONSTRAINT ck_schedule_segments_break_rule CHECK (
        (break_slot IS NULL AND work_segment_sequence IS NULL AND break_minutes = 0)
        OR (
            break_slot IS NOT NULL
            AND segment_type IN ('PAID_BREAK', 'UNPAID_BREAK')
            AND break_slot IN ('FIRST_BREAK', 'MEAL_BREAK', 'SECOND_BREAK', 'OT_BREAK')
            AND (
                break_slot NOT IN ('FIRST_BREAK', 'SECOND_BREAK', 'OT_BREAK')
                OR segment_type = 'PAID_BREAK'
            )
            AND work_segment_sequence IS NOT NULL
            AND break_minutes > 0
        )
    );

COMMIT;
