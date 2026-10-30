"""Support operational group soft deletion."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d9a0123e4f56"
down_revision = "c8f9012d3e45"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("operational_groups", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), schema="core")
    op.add_column(
        "operational_groups",
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        schema="core",
    )
    op.create_foreign_key(
        "fk_operational_groups_deleted_by", "operational_groups", "users",
        ["deleted_by"], ["id"], source_schema="core", referent_schema="identity",
    )


def downgrade():
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM core.operational_groups WHERE deleted_at IS NOT NULL) THEN
                RAISE EXCEPTION 'Restore deleted operational groups before downgrading.';
            END IF;
        END $$;
    """)
    op.drop_constraint("fk_operational_groups_deleted_by", "operational_groups", schema="core", type_="foreignkey")
    op.drop_column("operational_groups", "deleted_by", schema="core")
    op.drop_column("operational_groups", "deleted_at", schema="core")
