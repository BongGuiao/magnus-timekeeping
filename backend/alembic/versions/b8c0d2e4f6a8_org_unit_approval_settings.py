"""Default-enabled org-unit approvers and descendant exclusions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b8c0d2e4f6a8"
down_revision = "a7b9c1d3e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "org_units",
        sa.Column("manager_is_approver", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="core",
    )
    op.add_column(
        "org_units",
        sa.Column(
            "excluded_approval_org_unit_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("org_units", "excluded_approval_org_unit_ids", schema="core")
    op.drop_column("org_units", "manager_is_approver", schema="core")
