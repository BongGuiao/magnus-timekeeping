"""Persist the actual approver for supervisor approval returns."""
from alembic import op

revision = "c2e4a6b8d0f1"
down_revision = "b1d3f5a7c9e2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE attendance.overtime_applications ADD COLUMN IF NOT EXISTS approved_by_id uuid")
    op.execute("ALTER TABLE leave_mgmt.leave_applications ADD COLUMN IF NOT EXISTS approved_by_id uuid")
    op.execute("CREATE INDEX IF NOT EXISTS ix_attendance_overtime_applications_approved_by_id ON attendance.overtime_applications (approved_by_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_leave_mgmt_leave_applications_approved_by_id ON leave_mgmt.leave_applications (approved_by_id)")


def downgrade():
    op.drop_index("ix_attendance_overtime_applications_approved_by_id", table_name="overtime_applications", schema="attendance")
    op.drop_index("ix_leave_mgmt_leave_applications_approved_by_id", table_name="leave_applications", schema="leave_mgmt")
    op.drop_column("overtime_applications", "approved_by_id", schema="attendance")
    op.drop_column("leave_applications", "approved_by_id", schema="leave_mgmt")
