"""Add missing-punch correction requests and supervisor permissions."""
from alembic import op
import sqlalchemy as sa

revision = "a3d4e5f6b7c8"
down_revision = "f2c3d4e5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "correction_requests",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("employee_id", sa.UUID(), sa.ForeignKey("hr.employees.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("attendance_record_id", sa.UUID(), sa.ForeignKey("attendance.attendance_records.id")),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("original_clock_in_at", sa.DateTime(timezone=True)),
        sa.Column("original_clock_out_at", sa.DateTime(timezone=True)),
        sa.Column("requested_clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_clock_out_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("supporting_reference", sa.String(500)),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reviewed_by", sa.UUID(), sa.ForeignKey("identity.users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_notes", sa.Text()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_corrections_status"),
        sa.CheckConstraint("requested_clock_out_at > requested_clock_in_at", name="ck_corrections_period"),
        schema="attendance",
    )
    op.create_index(
        "uq_corrections_pending_employee_date", "correction_requests", ["employee_id", "work_date"],
        unique=True, schema="attendance", postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.execute("""
        INSERT INTO identity.permissions(permission_code, module_code, action_code, permission_name, description)
        VALUES
          ('attendance.correct_own', 'attendance', 'correct_own', 'File own missing-punch corrections',
           'File and view missing-punch correction requests for the signed-in employee.'),
          ('attendance.approve_corrections_team', 'attendance', 'approve_corrections_team',
           'Approve team missing-punch corrections', 'Approve or reject missing-punch requests of current direct reports.')
        ON CONFLICT (permission_code) DO UPDATE SET
          module_code=EXCLUDED.module_code, action_code=EXCLUDED.action_code,
          permission_name=EXCLUDED.permission_name, description=EXCLUDED.description, is_active=true
    """)
    op.execute("""
        INSERT INTO identity.role_permissions(role_id, permission_id, allowed)
        SELECT r.id, p.id, true FROM identity.roles r CROSS JOIN identity.permissions p
        WHERE (p.permission_code='attendance.correct_own' AND upper(r.role_code) IN ('EMPLOYEE', 'SUPERVISOR'))
           OR (p.permission_code='attendance.approve_corrections_team' AND upper(r.role_code)='SUPERVISOR')
        ON CONFLICT (role_id, permission_id) DO UPDATE SET allowed=EXCLUDED.allowed
    """)


def downgrade():
    op.execute("""
        DELETE FROM identity.role_permissions WHERE permission_id IN (
            SELECT id FROM identity.permissions WHERE permission_code IN
                ('attendance.correct_own', 'attendance.approve_corrections_team')
        )
    """)
    op.execute("""
        DELETE FROM identity.permissions WHERE permission_code IN
            ('attendance.correct_own', 'attendance.approve_corrections_team')
    """)
    op.drop_table("correction_requests", schema="attendance")
