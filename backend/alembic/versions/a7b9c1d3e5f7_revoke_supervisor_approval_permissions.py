"""Revoke team approval permissions from the SUPERVISOR role.

Approvers are the org-unit managers resolved by approval routing; those managers
receive the team approval permissions from their manager assignment instead.
"""
from alembic import op

revision = "a7b9c1d3e5f7"
down_revision = "f4a6b8c0d2e4"
branch_labels = None
depends_on = None

SUPERVISOR_APPROVAL_PERMISSIONS = (
    "overtime.approve_team",
    "leave.approve_team",
    "official_business.approve_team",
    "schedule.approve_emergency",
    "attendance.approve_corrections_team",
)
_CODES = ", ".join(f"'{code}'" for code in SUPERVISOR_APPROVAL_PERMISSIONS)


def upgrade():
    op.execute(f"""
        DELETE FROM identity.role_permissions rp
        USING identity.roles r, identity.permissions p
        WHERE rp.role_id = r.id
          AND rp.permission_id = p.id
          AND upper(r.role_code) = 'SUPERVISOR'
          AND p.permission_code IN ({_CODES})
    """)


def downgrade():
    op.execute(f"""
        INSERT INTO identity.role_permissions(role_id, permission_id, allowed)
        SELECT r.id, p.id, true
        FROM identity.roles r CROSS JOIN identity.permissions p
        WHERE upper(r.role_code) = 'SUPERVISOR'
          AND p.permission_code IN ({_CODES})
        ON CONFLICT (role_id, permission_id) DO UPDATE SET allowed = EXCLUDED.allowed
    """)
