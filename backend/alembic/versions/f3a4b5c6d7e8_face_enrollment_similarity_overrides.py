"""Record HR Admin approvals of face enrollments that resemble another employee."""

from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS biometric.face_enrollment_similarity_overrides (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            enrollment_id uuid NOT NULL,
            employee_id uuid NOT NULL,
            employee_no varchar(30) NOT NULL,
            conflicting_employee_ids uuid[] NOT NULL,
            conflicting_employee_nos varchar(30)[] NOT NULL,
            closest_distance double precision NOT NULL,
            threshold double precision NOT NULL,
            reason varchar(500) NOT NULL,
            approved_by uuid NOT NULL,
            approved_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_face_enrollment_overrides_conflicts CHECK (
                cardinality(conflicting_employee_ids) > 0
                AND cardinality(conflicting_employee_ids) = cardinality(conflicting_employee_nos)
            ),
            CONSTRAINT ck_face_enrollment_overrides_reason CHECK (length(btrim(reason)) > 0)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_face_enrollment_overrides_employee_time
        ON biometric.face_enrollment_similarity_overrides (employee_id, approved_at)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM biometric.face_enrollment_similarity_overrides) THEN
                RAISE EXCEPTION 'Cannot remove face similarity override history. Roll back application code and retain this table.';
            END IF;
        END
        $$
    """)
    op.drop_table("face_enrollment_similarity_overrides", schema="biometric")
