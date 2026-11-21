"""Create persistent tardiness cases and immutable notice snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c6f8a0b2d4e6"
down_revision = "b5e7f9a1c3d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "notice_templates",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("sanitized_html", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", uuid, sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("module = 'TARDINESS'", name="ck_notice_templates_module"),
        schema="attendance",
    )
    op.create_index(
        "uq_notice_templates_active_module", "notice_templates", ["module"], unique=True,
        postgresql_where=sa.text("is_active"), schema="attendance",
    )
    op.create_table(
        "tardiness_cases",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("employee_id", uuid, sa.ForeignKey("hr.employees.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("employee_id", "period_start", name="uq_tardiness_case_employee_period"),
        schema="attendance",
    )
    op.create_table(
        "issued_notices",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("case_id", uuid, sa.ForeignKey("attendance.tardiness_cases.id"), nullable=False),
        sa.Column("employee_id", uuid, sa.ForeignKey("hr.employees.id"), nullable=False),
        sa.Column("template_id", uuid, sa.ForeignKey("attendance.notice_templates.id"), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False),
        sa.Column("field_values", postgresql.JSONB(), nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("issued_by", uuid, sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("receipt_method", sa.String(200)),
        sa.Column("receipt_recorded_by", uuid, sa.ForeignKey("identity.users.id")),
        sa.Column("receipt_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("response_text", sa.Text()),
        sa.Column("response_submitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("case_id", name="uq_issued_notice_case"),
        sa.CheckConstraint(
            "(received_at IS NULL AND due_at IS NULL AND receipt_method IS NULL) OR "
            "(received_at IS NOT NULL AND due_at IS NOT NULL AND receipt_method IS NOT NULL)",
            name="ck_notice_receipt_fields",
        ),
        schema="attendance",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM attendance.issued_notices) OR "
        "EXISTS (SELECT 1 FROM attendance.notice_templates) OR "
        "EXISTS (SELECT 1 FROM attendance.tardiness_cases) THEN "
        "RAISE EXCEPTION 'Cannot remove notice workflow while records exist'; END IF; END $$"
    )
    op.drop_table("issued_notices", schema="attendance")
    op.drop_table("tardiness_cases", schema="attendance")
    op.drop_index("uq_notice_templates_active_module", table_name="notice_templates", schema="attendance")
    op.drop_table("notice_templates", schema="attendance")
