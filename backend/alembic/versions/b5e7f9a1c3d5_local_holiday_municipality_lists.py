"""Add municipality inclusion and exclusion lists to local holidays."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b5e7f9a1c3d5"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def _create_scope_index(with_lists: bool) -> None:
    lists = (
        ", (CASE WHEN holiday_type = 'LOCAL' THEN md5(included_municipalities::text) ELSE '' END)"
        ", (CASE WHEN holiday_type = 'LOCAL' THEN md5(excluded_municipalities::text) ELSE '' END)"
        if with_lists else ""
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_holidays_calendar_date_name_scope ON core.holidays ("
        "holiday_calendar_id, holiday_date, holiday_name, "
        "(CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_region_code, upper(btrim(region)), '') ELSE '' END), "
        "(CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_province_code, upper(btrim(province)), '') ELSE '' END), "
        "(CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_city_code, upper(btrim(city)), '') ELSE '' END), "
        "(CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(ncr_district, '') ELSE '' END)"
        f"{lists})"
    )


def upgrade() -> None:
    for column in ("included_municipalities", "excluded_municipalities"):
        op.add_column(
            "holidays",
            sa.Column(column, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            schema="core",
        )
        op.create_check_constraint(
            f"ck_holidays_{column}_array", "holidays",
            f"jsonb_typeof({column}) = 'array'", schema="core",
        )
    op.execute("DROP INDEX core.uq_holidays_calendar_date_name_scope")
    _create_scope_index(True)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM core.holidays WHERE "
        "included_municipalities <> '[]'::jsonb OR excluded_municipalities <> '[]'::jsonb) "
        "THEN RAISE EXCEPTION 'Cannot downgrade while municipality lists contain data'; "
        "END IF; END $$"
    )
    op.execute("DROP INDEX core.uq_holidays_calendar_date_name_scope")
    _create_scope_index(False)
    for column in ("excluded_municipalities", "included_municipalities"):
        op.drop_constraint(f"ck_holidays_{column}_array", "holidays", schema="core")
        op.drop_column("holidays", column, schema="core")
