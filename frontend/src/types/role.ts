export const dashboardRoles = [
  'administrator',
  'manager',
  'supervisor',
  'employee',
] as const

export type DashboardRole = (typeof dashboardRoles)[number]

export function isDashboardRole(value: unknown): value is DashboardRole {
  return typeof value === 'string' && dashboardRoles.some((role) => role === value)
}

export function normalizeDashboardRole(value: string | null): DashboardRole {
  switch (value?.trim().toLowerCase().replaceAll('-', '_')) {
    case 'admin':
    case 'administrator':
    case 'system_admin':
    case 'system_administrator':
    case 'hr_admin':
      return 'administrator'
    case 'manager':
      return 'manager'
    case 'supervisor':
      return 'supervisor'
    case 'employee':
    case 'user':
    default:
      return 'employee'
  }
}

export function getAvailableRoleCodes(): string[] {
  const storedRoleCodes = localStorage.getItem('role_codes')
  if (storedRoleCodes) {
    try {
      const roleCodes: unknown = JSON.parse(storedRoleCodes)
      if (Array.isArray(roleCodes) && roleCodes.every((roleCode) => typeof roleCode === 'string')) {
        return roleCodes
      }
    } catch {
      // Ignore invalid cached role codes and fall back to the legacy role value.
    }
  }

  return [localStorage.getItem('role') ?? 'user']
}

export function getPermissionCodes(): string[] {
  const storedPermissionCodes = localStorage.getItem('permission_codes')
  if (!storedPermissionCodes) return []
  try {
    const permissionCodes: unknown = JSON.parse(storedPermissionCodes)
    return Array.isArray(permissionCodes)
      ? permissionCodes.filter((permissionCode): permissionCode is string => typeof permissionCode === 'string')
      : []
  } catch {
    return []
  }
}

export function hasPermission(permissionCode: string): boolean {
  return getPermissionCodes().includes(permissionCode)
}

export function hasAnyPermission(permissionCodes: string[]): boolean {
  const grantedPermissions = new Set(getPermissionCodes())
  return permissionCodes.some((permissionCode) => grantedPermissions.has(permissionCode))
}

export function canPreviewDashboardRoles(): boolean {
  return hasPermission('system.manage')
}

export function hasEmployeeRoleCode(): boolean {
  return getAvailableRoleCodes().some((roleCode) => roleCode.trim().toUpperCase() === 'EMPLOYEE')
}

export function getSelectedDashboardRoleCode(): string {
  const roleCodes = getAvailableRoleCodes()
  const selectedRoleCode = localStorage.getItem('dashboard_role_code')
  if (selectedRoleCode && roleCodes.includes(selectedRoleCode)) return selectedRoleCode

  if (canPreviewDashboardRoles()) {
    const legacyPreviewRole = localStorage.getItem('dashboard_role')
    const legacySelection = roleCodes.find(
      (roleCode) => normalizeDashboardRole(roleCode) === normalizeDashboardRole(legacyPreviewRole),
    )
    if (legacySelection) return legacySelection
  }

  const appRole = localStorage.getItem('role')
  return roleCodes.find((roleCode) => normalizeDashboardRole(roleCode) === normalizeDashboardRole(appRole))
    ?? roleCodes[0]
    ?? ''
}

export function getSelectedDashboardRole(): DashboardRole {
  return normalizeDashboardRole(getSelectedDashboardRoleCode())
}
