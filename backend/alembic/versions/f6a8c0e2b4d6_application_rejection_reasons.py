"""Store reviewer rejection reasons for applications."""

from alembic import op
import sqlalchemy as sa

revision = "f6a8c0e2b4d6"
down_revision = "e4f6a8b0c2d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leave_applications", sa.Column("rejection_reason", sa.Text(), nullable=True), schema="leave_mgmt")
    op.add_column("overtime_applications", sa.Column("rejection_reason", sa.Text(), nullable=True), schema="attendance")
    op.add_column("official_business_requests", sa.Column("rejection_reason", sa.Text(), nullable=True), schema="attendance")


def downgrade():
    op.drop_column("official_business_requests", "rejection_reason", schema="attendance")
    op.drop_column("overtime_applications", "rejection_reason", schema="attendance")
    op.drop_column("leave_applications", "rejection_reason", schema="leave_mgmt")
