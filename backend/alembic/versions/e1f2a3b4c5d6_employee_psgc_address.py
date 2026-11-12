"""Add PSGC address selection to employee personal details."""
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hr.employee_personal_details
            ADD COLUMN IF NOT EXISTS region varchar(100),
            ADD COLUMN IF NOT EXISTS psgc_region_code varchar(9),
            ADD COLUMN IF NOT EXISTS psgc_province_code varchar(9),
            ADD COLUMN IF NOT EXISTS psgc_city_code varchar(9),
            ADD COLUMN IF NOT EXISTS psgc_barangay_code varchar(9)
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_employee_personal_details_psgc_codes'
                  AND conrelid = 'hr.employee_personal_details'::regclass
            ) THEN
                ALTER TABLE hr.employee_personal_details
                    ADD CONSTRAINT ck_employee_personal_details_psgc_codes CHECK (
                        (psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$')
                        AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$')
                        AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$')
                        AND (psgc_barangay_code IS NULL OR psgc_barangay_code ~ '^[0-9]{9}$')
                    );
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.drop_constraint("ck_employee_personal_details_psgc_codes", "employee_personal_details", schema="hr")
    for column in ("psgc_barangay_code", "psgc_city_code", "psgc_province_code", "psgc_region_code", "region"):
        op.drop_column("employee_personal_details", column, schema="hr")
