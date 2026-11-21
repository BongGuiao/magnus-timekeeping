"""Allow return-to-work notice templates."""

from alembic import op

revision = "d7a9c1e3f5b7"
down_revision = "c6f8a0b2d4e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_notice_templates_module", "notice_templates", schema="attendance")
    op.create_check_constraint(
        "ck_notice_templates_module", "notice_templates",
        "module IN ('TARDINESS', 'RETURN_TO_WORK')", schema="attendance",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM attendance.notice_templates WHERE module = 'RETURN_TO_WORK') "
        "THEN RAISE EXCEPTION 'Cannot remove return-to-work support while templates exist'; END IF; END $$"
    )
    op.drop_constraint("ck_notice_templates_module", "notice_templates", schema="attendance")
    op.create_check_constraint(
        "ck_notice_templates_module", "notice_templates", "module = 'TARDINESS'", schema="attendance",
    )
