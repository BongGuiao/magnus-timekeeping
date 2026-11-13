"""Link automatically verified face samples to their original HR approval."""

from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE biometric.face_enrollment_similarity_overrides
        ADD COLUMN IF NOT EXISTS source_override_id uuid
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM biometric.face_enrollment_similarity_overrides
                WHERE source_override_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Cannot remove face approval continuation history. Roll back application code and retain this column.';
            END IF;
        END
        $$
    """)
    op.drop_column("face_enrollment_similarity_overrides", "source_override_id", schema="biometric")
