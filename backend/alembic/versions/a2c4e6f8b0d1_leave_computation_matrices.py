"""Store company leave computation matrices without applying them."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "a2c4e6f8b0d1"
down_revision = "f6a8c0e2b4d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leave_computation_matrices",
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("core.companies.id"), primary_key=True),
        sa.Column("ranges", JSONB(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="leave_mgmt",
    )


def downgrade():
    op.drop_table("leave_computation_matrices", schema="leave_mgmt")
