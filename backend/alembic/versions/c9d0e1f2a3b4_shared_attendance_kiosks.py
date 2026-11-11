"""Registered shared attendance kiosks."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c9d0e1f2a3b4"
down_revision = "b8c0d2e4f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "kiosk_devices",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("device_name", sa.String(100), nullable=False),
        sa.Column("public_key_jwk", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pairing_code", sa.String(32), nullable=False, unique=True),
        sa.Column("pairing_expires_at", timestamp, nullable=False),
        sa.Column("company_id", uuid, sa.ForeignKey("core.companies.id")),
        sa.Column("location_id", uuid),
        sa.Column("approved_by", uuid),
        sa.Column("approved_at", timestamp),
        sa.Column("revoked_by", uuid),
        sa.Column("revoked_at", timestamp),
        sa.Column("last_seen_at", timestamp),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REVOKED')", name="ck_kiosk_status"),
        sa.CheckConstraint(
            "status != 'APPROVED' OR (company_id IS NOT NULL AND location_id IS NOT NULL)",
            name="ck_kiosk_approved_scope",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "location_id"], ["core.locations.company_id", "core.locations.id"],
            name="fk_kiosk_location_company",
        ),
        schema="identity",
    )
    op.create_table(
        "kiosk_challenges",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("device_id", uuid, sa.ForeignKey("identity.kiosk_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("consumed_at", timestamp),
        sa.CheckConstraint("purpose IN ('STATUS', 'IDENTIFY', 'CLOCK', 'BREAK')", name="ck_kiosk_challenge_purpose"),
        schema="identity",
    )
    op.create_index("ix_identity_kiosk_challenges_device_id", "kiosk_challenges", ["device_id"], schema="identity")
    op.create_index("ix_identity_kiosk_challenges_expires_at", "kiosk_challenges", ["expires_at"], schema="identity")


def downgrade() -> None:
    op.drop_table("kiosk_challenges", schema="identity")
    op.drop_table("kiosk_devices", schema="identity")
