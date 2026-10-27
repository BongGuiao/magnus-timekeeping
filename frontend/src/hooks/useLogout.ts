interface UseLogoutOptions {
  onLoggedOut?: () => void
}

export function useLogout(options: UseLogoutOptions = {}) {
  function logout() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('role')
    localStorage.removeItem('role_codes')
    localStorage.removeItem('permission_codes')
    localStorage.removeItem('dashboard_role')
    localStorage.removeItem('dashboard_role_code')
    localStorage.removeItem('employee_name')
    localStorage.removeItem('employee_code')
    options.onLoggedOut?.()
  }

  return { logout }
}
