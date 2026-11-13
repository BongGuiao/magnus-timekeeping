"""Persist face enrollment resets independently of Elasticsearch."""

from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS biometric.face_enrollment_resets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id uuid NOT NULL,
            employee_no varchar(30) NOT NULL,
            reset_by uuid NOT NULL,
            reset_at timestamptz NOT NULL DEFAULT now(),
            sample_ids uuid[] NOT NULL,
            sample_count integer NOT NULL,
            reason varchar(500) NOT NULL,
            profile_photo_cleared boolean NOT NULL DEFAULT false,
            CONSTRAINT ck_face_enrollment_resets_samples
                CHECK (sample_count > 0 AND cardinality(sample_ids) = sample_count),
            CONSTRAINT ck_face_enrollment_resets_reason CHECK (length(btrim(reason)) > 0)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_face_enrollment_resets_employee_time
        ON biometric.face_enrollment_resets (employee_id, reset_at)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM biometric.face_enrollment_resets) THEN
                RAISE EXCEPTION 'Cannot remove face reset audit history. Roll back application code and retain this table.';
            END IF;
        END
        $$
    """)
    op.drop_table("face_enrollment_resets", schema="biometric")
