-- Mirrors alembic revision a7b9c1d3e5f7 for databases maintained with manual SQL.
-- Approvers are org-unit managers; the SUPERVISOR role no longer grants team approvals.
BEGIN;

DELETE FROM identity.role_permissions rp
USING identity.roles r, identity.permissions p
WHERE rp.role_id = r.id
  AND rp.permission_id = p.id
  AND upper(r.role_code) = 'SUPERVISOR'
  AND p.permission_code IN (
      'overtime.approve_team',
      'leave.approve_team',
      'official_business.approve_team',
      'schedule.approve_emergency',
      'attendance.approve_corrections_team'
  );

COMMIT;
