"""Separate employee personal and government information."""
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.employee_personal_details (
            employee_id uuid PRIMARY KEY REFERENCES hr.employees(id) ON DELETE CASCADE,
            bank_account_no varchar(100),
            sss_no varchar(30),
            pagibig_no varchar(30),
            philhealth_no varchar(30),
            tin_no varchar(30),
            address_line_1 varchar(255),
            address_line_2 varchar(255),
            barangay varchar(100),
            city_municipality varchar(100),
            province varchar(100),
            postal_code varchar(20),
            civil_status varchar(20),
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid,
            updated_at timestamptz NOT NULL DEFAULT now(),
            updated_by uuid,
            CONSTRAINT ck_employee_personal_details_civil_status
                CHECK (civil_status IN ('SINGLE', 'MARRIED', 'WIDOWED', 'SEPARATED', 'DIVORCED', 'OTHER'))
        )
    """)


def downgrade() -> None:
    op.drop_table("employee_personal_details", schema="hr")
