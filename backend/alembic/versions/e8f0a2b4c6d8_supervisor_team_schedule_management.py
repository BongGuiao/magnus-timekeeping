"""Allow supervisors to manage direct reports' schedule assignments."""
from alembic import op

revision = "e8f0a2b4c6d8"
down_revision = "d7a9c1e3f5b7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO identity.permissions
            (permission_code, module_code, action_code, permission_name, description)
        VALUES ('schedule.manage_team', 'schedule', 'manage_team',
                'Manage team schedule assignments',
                'Manage schedule assignments for current direct reports.')
        ON CONFLICT (permission_code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO identity.role_permissions (role_id, permission_id, allowed)
        SELECT r.id, p.id, true
        FROM identity.roles r CROSS JOIN identity.permissions p
        WHERE upper(r.role_code) = 'SUPERVISOR'
          AND p.permission_code = 'schedule.manage_team'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """)


def downgrade():
    op.execute("""
        DELETE FROM identity.role_permissions
        WHERE permission_id IN (
            SELECT id FROM identity.permissions WHERE permission_code = 'schedule.manage_team'
        )
    """)
    op.execute("DELETE FROM identity.permissions WHERE permission_code = 'schedule.manage_team'")
