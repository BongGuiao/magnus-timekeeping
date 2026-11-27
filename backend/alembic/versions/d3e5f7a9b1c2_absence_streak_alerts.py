"""Store consecutive absence alerts and per-user dismissals."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d3e5f7a9b1c2"
down_revision = "c2e4a6b8d0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "absence_streak_alerts",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("employee_id", uuid, sa.ForeignKey("hr.employees.id"), nullable=False),
        sa.Column("company_id", uuid, sa.ForeignKey("core.companies.id"), nullable=False),
        sa.Column("first_absence_date", sa.Date(), nullable=False),
        sa.Column("second_absence_date", sa.Date(), nullable=False),
        sa.Column("third_absence_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("employee_id", "first_absence_date", name="uq_absence_streak_employee_start"),
        schema="attendance",
    )
    op.create_table(
        "absence_streak_dismissals",
        sa.Column("alert_id", uuid, sa.ForeignKey("attendance.absence_streak_alerts.id"), primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("identity.users.id"), primary_key=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="attendance",
    )
    op.create_index(
        "ix_attendance_valid_absence_user_date", "attendance_records", ["user_id", "work_date"],
        postgresql_where=sa.text("is_absent AND record_status = 'VALID'"), schema="attendance",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM attendance.absence_streak_alerts) "
        "THEN RAISE EXCEPTION 'Cannot remove absence alerts while records exist'; END IF; END $$"
    )
    op.drop_index("ix_attendance_valid_absence_user_date", table_name="attendance_records", schema="attendance")
    op.drop_table("absence_streak_dismissals", schema="attendance")
    op.drop_table("absence_streak_alerts", schema="attendance")
