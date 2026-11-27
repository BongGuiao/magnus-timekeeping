"""Store mobile push devices and absence alert delivery state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e4f6a8b0c2d4"
down_revision = "d3e5f7a9b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "mobile_push_devices",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", uuid, sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("token", sa.String(255), nullable=False, unique=True),
        sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="identity",
    )
    op.create_table(
        "absence_push_deliveries",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("alert_id", uuid, sa.ForeignKey("attendance.absence_streak_alerts.id"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("device_id", uuid, sa.ForeignKey("identity.mobile_push_devices.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("receipt_id", sa.String(255)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("alert_id", "user_id", "device_id", name="uq_absence_push_recipient_device"),
        schema="attendance",
    )
    op.create_index("ix_absence_push_due", "absence_push_deliveries", ["state", "next_attempt_at"], schema="attendance")


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM attendance.absence_push_deliveries) "
        "OR EXISTS (SELECT 1 FROM identity.mobile_push_devices) "
        "THEN RAISE EXCEPTION 'Cannot remove push data while records exist'; END IF; END $$"
    )
    op.drop_index("ix_absence_push_due", table_name="absence_push_deliveries", schema="attendance")
    op.drop_table("absence_push_deliveries", schema="attendance")
    op.drop_table("mobile_push_devices", schema="identity")
