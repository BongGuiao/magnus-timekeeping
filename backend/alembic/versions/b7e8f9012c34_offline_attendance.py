"""Add offline authorization and idempotent attendance event storage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7e8f9012c34"
down_revision = "a6f2d9c4e781"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offline_permits",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("device_id", sa.UUID(), sa.ForeignKey("identity.devices.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        schema="attendance",
    )
    op.create_index("ix_attendance_offline_permits_user_id", "offline_permits", ["user_id"], schema="attendance")
    op.create_table(
        "offline_punch_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("permit_id", sa.UUID(), sa.ForeignKey("attendance.offline_permits.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("identity.users.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("signature", sa.String(86), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("attendance_id", sa.UUID(), sa.ForeignKey("attendance.attendance_records.id"), nullable=True),
        sa.Column("encrypted_photo", sa.LargeBinary(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), sa.ForeignKey("identity.users.id"), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("permit_id", "sequence", name="uq_offline_event_sequence"),
        sa.CheckConstraint("status IN ('ACCEPTED', 'NEEDS_REVIEW', 'REJECTED')", name="ck_offline_event_status"),
        schema="attendance",
    )
    op.create_index("ix_attendance_offline_punch_events_user_id", "offline_punch_events", ["user_id"], schema="attendance")
    op.create_index("ix_attendance_offline_punch_events_status", "offline_punch_events", ["status"], schema="attendance")


def downgrade() -> None:
    op.drop_table("offline_punch_events", schema="attendance")
    op.drop_table("offline_permits", schema="attendance")
