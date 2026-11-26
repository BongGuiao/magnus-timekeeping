BEGIN;

ALTER TABLE attendance.overtime_applications ADD COLUMN IF NOT EXISTS approved_by_id uuid;
ALTER TABLE leave_mgmt.leave_applications ADD COLUMN IF NOT EXISTS approved_by_id uuid;

CREATE INDEX IF NOT EXISTS ix_attendance_overtime_applications_approved_by_id
    ON attendance.overtime_applications (approved_by_id);
CREATE INDEX IF NOT EXISTS ix_leave_mgmt_leave_applications_approved_by_id
    ON leave_mgmt.leave_applications (approved_by_id);

-- Do not infer old approvers from updated_by or the currently assigned route.
COMMIT;
