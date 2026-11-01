"""Add regular-holiday pay attendance rule and unworked holiday pay components."""

from alembic import op
import sqlalchemy as sa

from app.filemaintenance.schedule.infrastructure.db_model import PositiveMinutes

revision = "e1b2c3d4f5a6"
down_revision = "d9a0123e4f56"
branch_labels = None
depends_on = None

EARNING_COMPONENTS = (
    "'REGULAR', 'PAID_LEAVE', 'OFFICIAL_BUSINESS', 'REST_DAY', 'SPECIAL_DAY', "
    "'HOLIDAY', 'ORDINARY_OT', 'REST_DAY_OT', 'SPECIAL_DAY_OT', 'HOLIDAY_OT', "
    "'NIGHT_REGULAR', 'NIGHT_OT'"
)
CUTOFF_RESULT_COLUMNS = (
    "unworked_holiday_minutes",
    "unworked_double_holiday_minutes",
    "disqualified_holiday_minutes",
)


def upgrade():
    op.add_column(
        "company_system_parameters",
        sa.Column(
            "holiday_pay_attendance_rule",
            sa.String(length=20),
            server_default=sa.text("'BEFORE_ONLY'"),
            nullable=False,
        ),
        schema="payroll",
    )
    op.create_check_constraint(
        "ck_payroll_company_system_parameters_holiday_pay_rule",
        "company_system_parameters",
        "holiday_pay_attendance_rule IN ('BEFORE_ONLY', 'BEFORE_AND_AFTER')",
        schema="payroll",
    )

    for column in CUTOFF_RESULT_COLUMNS:
        op.add_column(
            "employee_cutoff_results",
            sa.Column(column, PositiveMinutes(), server_default=sa.text("0"), nullable=False),
            schema="payroll",
        )

    op.drop_constraint(
        "ck_payroll_earning_rules_component", "earning_rules", schema="payroll", type_="check"
    )
    op.create_check_constraint(
        "ck_payroll_earning_rules_component",
        "earning_rules",
        f"component_code IN ({EARNING_COMPONENTS}, 'UNWORKED_HOLIDAY', 'UNWORKED_DOUBLE_HOLIDAY')",
        schema="payroll",
    )
    # Statutory unworked regular-holiday pay: 100% of the daily wage, 200% on a double holiday.
    op.execute(
        """
        INSERT INTO payroll.earning_rules (
            payroll_group_id, component_code, multiplier, created_by, updated_by
        )
        SELECT groups.payroll_group_id, rules.component_code, rules.multiplier,
               groups.created_by, groups.created_by
        FROM (
            SELECT DISTINCT ON (payroll_group_id) payroll_group_id, created_by
            FROM payroll.earning_rules
            ORDER BY payroll_group_id, created_at
        ) AS groups
        CROSS JOIN (
            VALUES ('UNWORKED_HOLIDAY', 1.0000), ('UNWORKED_DOUBLE_HOLIDAY', 2.0000)
        ) AS rules (component_code, multiplier)
        ON CONFLICT (payroll_group_id, component_code) DO NOTHING
        """
    )


def downgrade():
    op.execute(
        "DELETE FROM payroll.earning_rules "
        "WHERE component_code IN ('UNWORKED_HOLIDAY', 'UNWORKED_DOUBLE_HOLIDAY')"
    )
    op.drop_constraint(
        "ck_payroll_earning_rules_component", "earning_rules", schema="payroll", type_="check"
    )
    op.create_check_constraint(
        "ck_payroll_earning_rules_component",
        "earning_rules",
        f"component_code IN ({EARNING_COMPONENTS})",
        schema="payroll",
    )
    for column in CUTOFF_RESULT_COLUMNS:
        op.drop_column("employee_cutoff_results", column, schema="payroll")
    op.drop_constraint(
        "ck_payroll_company_system_parameters_holiday_pay_rule",
        "company_system_parameters",
        schema="payroll",
        type_="check",
    )
    op.drop_column("company_system_parameters", "holiday_pay_attendance_rule", schema="payroll")
