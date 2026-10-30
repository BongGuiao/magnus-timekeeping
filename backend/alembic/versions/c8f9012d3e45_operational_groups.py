"""Replace fixed operational groups with company-specific lookup records."""

from alembic import op
import sqlalchemy as sa

revision = "c8f9012d3e45"
down_revision = "b7e8f9012c34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_groups",
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("core.companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("operational_group", sa.String(30), primary_key=True),
        sa.Column("display_name", sa.String(50), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("operational_group ~ '^[A-Z0-9_-]+$'", name="ck_operational_groups_code"),
        sa.CheckConstraint("length(btrim(display_name)) > 0", name="ck_operational_groups_display_name"),
        sa.CheckConstraint("sort_order >= 0", name="ck_operational_groups_sort_order"),
        schema="core",
    )
    op.execute("""
        INSERT INTO core.operational_groups
            (company_id, operational_group, display_name, sort_order, is_active)
        SELECT c.id, g.code, g.code, g.sort_order, true
        FROM core.companies c
        CROSS JOIN (VALUES
            ('SLI', 0), ('SLR', 1), ('ASS', 2), ('MTT', 3), ('COLLECTION', 4),
            ('FLEET', 5), ('WAREHOUSE', 6), ('OFFICE', 7), ('OTHER', 8)
        ) AS g(code, sort_order)
    """)
    op.execute("""
        INSERT INTO core.operational_groups
            (company_id, operational_group, display_name, sort_order, is_active)
        SELECT DISTINCT company_id, operational_group, operational_group, 9, true
        FROM hr.employment_assignments
        WHERE operational_group IS NOT NULL
        ON CONFLICT (company_id, operational_group) DO NOTHING
    """)
    op.execute(
        "ALTER TABLE hr.employment_assignments "
        "DROP CONSTRAINT IF EXISTS ck_employment_assignments_operational_group"
    )
    op.create_foreign_key(
        "fk_assignment_operational_group", "employment_assignments", "operational_groups",
        ["company_id", "operational_group"], ["company_id", "operational_group"],
        source_schema="hr", referent_schema="core",
    )


def downgrade() -> None:
    # Refuse to discard configurable groups or assignments that the fixed list cannot represent.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM core.operational_groups
                WHERE operational_group NOT IN
                    ('SLI', 'SLR', 'ASS', 'MTT', 'COLLECTION', 'FLEET', 'WAREHOUSE', 'OFFICE', 'OTHER')
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade while custom operational groups exist.';
            END IF;
        END $$;
    """)
    op.drop_constraint("fk_assignment_operational_group", "employment_assignments", schema="hr", type_="foreignkey")
    op.create_check_constraint(
        "ck_employment_assignments_operational_group", "employment_assignments",
        "operational_group IS NULL OR operational_group IN "
        "('SLI', 'SLR', 'ASS', 'MTT', 'COLLECTION', 'FLEET', 'WAREHOUSE', 'OFFICE', 'OTHER')",
        schema="hr",
    )
    op.drop_table("operational_groups", schema="core")
