"""Separate employee filing from attendance approval deadlines."""

from alembic import op
import sqlalchemy as sa

revision = "f2c3d4e5a6b7"
down_revision = "e1b2c3d4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cutoffs", sa.Column("employee_filing_deadline", sa.DateTime(timezone=True), nullable=True),
        schema="payroll",
    )
    op.create_check_constraint(
        "ck_cutoffs_filing_before_approval", "cutoffs",
        "employee_filing_deadline IS NULL OR "
        "(attendance_deadline IS NOT NULL AND employee_filing_deadline <= attendance_deadline)",
        schema="payroll",
    )


def downgrade():
    op.drop_constraint("ck_cutoffs_filing_before_approval", "cutoffs", schema="payroll", type_="check")
    op.drop_column("cutoffs", "employee_filing_deadline", schema="payroll")
