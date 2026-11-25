"""Add combined rest-day and holiday payroll components."""
from alembic import op

revision = "f5b7d9e1a3c5"
down_revision = "e8f0a2b4c6d8"
branch_labels = None
depends_on = None

_COLUMNS = (
    "holiday_rest_minutes",
    "holiday_rest_ot_minutes",
    "double_holiday_rest_minutes",
    "double_holiday_rest_ot_minutes",
    "special_rest_minutes",
    "special_rest_ot_minutes",
)

_BASE_CODES = (
    "'REGULAR', 'PAID_LEAVE', 'OFFICIAL_BUSINESS', 'REST_DAY', 'SPECIAL_DAY', "
    "'HOLIDAY', 'ORDINARY_OT', 'REST_DAY_OT', 'SPECIAL_DAY_OT', 'HOLIDAY_OT', "
    "'NIGHT_REGULAR', 'NIGHT_OT', 'UNWORKED_HOLIDAY', 'UNWORKED_DOUBLE_HOLIDAY'"
)
_REST_CODES = (
    "'HOLIDAY_REST', 'HOLIDAY_REST_OT', 'DOUBLE_HOLIDAY_REST', "
    "'DOUBLE_HOLIDAY_REST_OT', 'SPECIAL_REST', 'SPECIAL_REST_OT'"
)


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX uq_rest_day_open_application ON attendance.overtime_applications "
        "(employee_id, attendance_date) WHERE is_active AND overtime_type = 'REST_DAY_WORK' "
        "AND status IN ('PENDING', 'APPROVED')"
    )
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE payroll.employee_cutoff_results ADD COLUMN {column} "
            "core.positive_minutes NOT NULL DEFAULT 0"
        )
    op.drop_constraint("ck_payroll_earning_rules_component", "earning_rules", schema="payroll", type_="check")
    op.create_check_constraint(
        "ck_payroll_earning_rules_component", "earning_rules",
        f"component_code IN ({_BASE_CODES}, {_REST_CODES})", schema="payroll",
    )


def downgrade():
    op.execute("DROP INDEX attendance.uq_rest_day_open_application")
    op.drop_constraint("ck_payroll_earning_rules_component", "earning_rules", schema="payroll", type_="check")
    op.create_check_constraint(
        "ck_payroll_earning_rules_component", "earning_rules",
        f"component_code IN ({_BASE_CODES})", schema="payroll",
    )
    for column in _COLUMNS:
        op.drop_column("employee_cutoff_results", column, schema="payroll")
