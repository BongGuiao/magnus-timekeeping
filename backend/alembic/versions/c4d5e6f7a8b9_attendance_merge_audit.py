"""Add immutable attendance merge audit records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c4d5e6f7a8b9"
down_revision = "a3d4e5f6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attendance_merges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("canonical_attendance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("schedule_template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_clock_out_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("merged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "merged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_attendance_id"],
            ["attendance.attendance_records.id"],
            name="fk_attendance_merges_canonical",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["hr.employees.id"],
            name="fk_attendance_merges_employee",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_template_id"], ["schedule.schedule_templates.id"],
            name="fk_attendance_merges_schedule_template",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merged_by"], ["identity.users.id"],
            name="fk_attendance_merges_merged_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attendance_merges"),
        sa.UniqueConstraint(
            "canonical_attendance_id",
            name="uq_attendance_merges_canonical",
        ),
        sa.UniqueConstraint(
            "employee_id", "work_date",
            name="uq_attendance_merges_employee_date",
        ),
        schema="attendance",
    )
    op.create_table(
        "attendance_merge_sources",
        sa.Column("merge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_attendance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["merge_id"], ["attendance.attendance_merges.id"],
            name="fk_attendance_merge_sources_merge",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_attendance_id"], ["attendance.attendance_records.id"],
            name="fk_attendance_merge_sources_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "merge_id", "source_attendance_id",
            name="pk_attendance_merge_sources",
        ),
        sa.UniqueConstraint(
            "source_attendance_id",
            name="uq_attendance_merge_sources_source",
        ),
        schema="attendance",
    )


def downgrade():
    op.drop_table("attendance_merge_sources", schema="attendance")
    op.drop_table("attendance_merges", schema="attendance")
