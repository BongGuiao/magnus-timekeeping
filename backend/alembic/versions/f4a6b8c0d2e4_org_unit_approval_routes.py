"""Store org-unit approval assignments and preserve existing pending routing."""

from alembic import op
import sqlalchemy as sa

revision = "f4a6b8c0d2e4"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedule_upload_batch_rows",
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("core.companies.id"), nullable=True),
        schema="schedule",
    )
    op.create_table(
        "approval_routes",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("routing_mode", sa.String(20), nullable=False),
        sa.Column("employee_id", sa.UUID(), sa.ForeignKey("hr.employees.id"), nullable=True),
        sa.Column("source_org_unit_id", sa.UUID(), sa.ForeignKey("core.org_units.id"), nullable=True),
        sa.Column("approver_org_unit_id", sa.UUID(), sa.ForeignKey("core.org_units.id"), nullable=True),
        sa.Column("approver_employee_id", sa.UUID(), sa.ForeignKey("hr.employees.id"), nullable=True),
        sa.Column("assigned_by", sa.UUID(), sa.ForeignKey("identity.users.id"), nullable=True),
        sa.Column("routing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "routing_mode IN ('LEGACY', 'ORG_UNIT', 'UNRESOLVED')",
            name="ck_approval_routes_mode",
        ),
        sa.CheckConstraint(
            "(routing_mode = 'ORG_UNIT' AND approver_employee_id IS NOT NULL) OR "
            "(routing_mode IN ('LEGACY', 'UNRESOLVED') AND approver_employee_id IS NULL)",
            name="ck_approval_routes_approver",
        ),
        sa.CheckConstraint(
            "routing_mode <> 'UNRESOLVED' OR (employee_id IS NOT NULL AND routing_error IS NOT NULL)",
            name="ck_approval_routes_unresolved",
        ),
        schema="core",
    )
    op.create_index(
        "uq_approval_routes_current",
        "approval_routes",
        ["resource_type", "resource_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_approval_routes_approver",
        "approval_routes",
        ["approver_employee_id", "resource_type"],
        schema="core",
        postgresql_where=sa.text("is_current AND routing_mode = 'ORG_UNIT'"),
    )
    for resource_type, table, condition in (
        ("leave_application", "leave_mgmt.leave_applications", "status = 'PENDING' AND is_active"),
        ("overtime_application", "attendance.overtime_applications", "status = 'PENDING' AND is_active"),
        ("official_business_request", "attendance.official_business_requests", "status = 'PENDING' AND is_active"),
        ("attendance_correction", "attendance.correction_requests", "status = 'PENDING'"),
        ("emergency_schedule_request", "schedule.emergency_schedule_requests", "status = 'PENDING_APPROVAL'"),
        ("schedule_upload_batch", "schedule.schedule_upload_batches", "TRUE"),
        ("invalid_attendance", "attendance.attendance_records", "record_status = 'INVALID'"),
    ):
        op.execute(
            f"INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode) "
            f"SELECT '{resource_type}', id, 'LEGACY' FROM {table} WHERE {condition}"
        )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM core.approval_routes WHERE routing_mode <> 'LEGACY') THEN
                RAISE EXCEPTION 'Cannot remove recorded organization approval routes.';
            END IF;
        END $$
        """
    )
    op.drop_index("ix_approval_routes_approver", table_name="approval_routes", schema="core")
    op.drop_index("uq_approval_routes_current", table_name="approval_routes", schema="core")
    op.drop_table("approval_routes", schema="core")
    op.drop_column("schedule_upload_batch_rows", "company_id", schema="schedule")
