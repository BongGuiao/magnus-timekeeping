BEGIN;

ALTER TABLE schedule.schedule_upload_batches
    DROP CONSTRAINT IF EXISTS ck_schedule_upload_batches_no_self_approval;

COMMIT;
