"""Track one regularization dashboard notification per HR user and day."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a9c3e5f7b1d2"
down_revision = "f5b7d9e1a3c5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "regularization_notifications",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("identity.users.id"), primary_key=True),
        sa.Column("notification_date", sa.Date(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        schema="hr",
    )


def downgrade():
    op.drop_table("regularization_notifications", schema="hr")
