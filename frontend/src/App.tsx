import { useState } from 'react'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Enrollment from './pages/Enrollment'
import Attendance from './pages/Attendance'
import Companies from './pages/Companies'
import OrgUnits from './pages/OrgUnits'
import Employees from './pages/Employees'
import Locations from './pages/Locations'
import Geofences from './pages/Geofences'
import LeaveManagement from './pages/LeaveManagement'
import EmployeeEntitlements from './pages/EmployeeEntitlements'
import LeaveApplication from './pages/LeaveApplication'
import OvertimeApplication from './pages/OvertimeApplication'
import OfficialBusiness from './pages/OfficialBusiness'
import PayrollGroups from './pages/PayrollGroups'
import PayrollCutoffs from './pages/PayrollCutoffs'
import ScheduleTemplates from './pages/ScheduleTemplates'
import RestDayPatterns from './pages/RestDayPatterns'
import ChangePassword from './pages/ChangePassword'
import type { NavView } from './components/dashboard/TopNav'
import { getSelectedDashboardRole, hasEmployeeRoleCode } from './types/role'

const navViews: NavView[] = [
  'dashboard', 'enrollment', 'attendance', 'companies', 'org-units', 'locations',
  'geofences', 'employees', 'leave-management', 'employee-entitlements',
  'leave-application', 'payroll-groups', 'payroll-cutoffs', 'schedule-templates', 'rest-day-patterns',
  'overtime-application', 'official-business', 'change-password',
]

function getStoredView(): NavView {
  const storedView = sessionStorage.getItem('active_view')
  return navViews.includes(storedView as NavView) ? storedView as NavView : 'dashboard'
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(localStorage.getItem('access_token')))
  const [employeeName, setEmployeeName] = useState(() => localStorage.getItem('employee_name') ?? '')
  const [view, setView] = useState<NavView>(getStoredView)

  function navigateTo(nextView: NavView) {
    sessionStorage.setItem('active_view', nextView)
    setView(nextView)
  }

  if (!isAuthenticated) {
    return (
      <Login
        onSuccess={(result) => {
          setEmployeeName(result.employee_name)
          setIsAuthenticated(true)
          navigateTo('dashboard')
        }}
      />
    )
  }

  const onLoggedOut = () => {
    sessionStorage.removeItem('active_view')
    setIsAuthenticated(false)
  }

  if (view === 'change-password') {
    return <ChangePassword employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'enrollment') {
    return <Enrollment employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'attendance') {
    return <Attendance employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'companies') {
    return <Companies employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'org-units') {
    return <OrgUnits employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'locations') {
    return <Locations employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'geofences') {
    return <Geofences employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'employees') {
    return <Employees employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'leave-management' || view === 'employee-entitlements') {
    if (localStorage.getItem('role') !== 'admin') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    if (view === 'leave-management') {
      return <LeaveManagement employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <EmployeeEntitlements employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'payroll-groups') {
    if (localStorage.getItem('role') !== 'admin') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <PayrollGroups employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'payroll-cutoffs') {
    if (localStorage.getItem('role') !== 'admin') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <PayrollCutoffs employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'schedule-templates') {
    if (localStorage.getItem('role') !== 'admin') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <ScheduleTemplates employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'rest-day-patterns') {
    if (localStorage.getItem('role') !== 'admin') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <RestDayPatterns employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
  }

  if (view === 'leave-application') {
    if (getSelectedDashboardRole() !== 'employee') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }

    return (
      <LeaveApplication
        employeeName={employeeName}
        previewOnly={!hasEmployeeRoleCode()}
        onNavigate={navigateTo}
        onLoggedOut={onLoggedOut}
      />
    )
  }

  if (view === 'overtime-application') {
    if (getSelectedDashboardRole() !== 'employee') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <OvertimeApplication
      employeeName={employeeName}
      previewOnly={!hasEmployeeRoleCode()}
      onNavigate={navigateTo}
      onLoggedOut={onLoggedOut}
    />
  }

  if (view === 'official-business') {
    if (getSelectedDashboardRole() !== 'employee') {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
    }
    return <OfficialBusiness
      employeeName={employeeName}
      previewOnly={!hasEmployeeRoleCode()}
      onNavigate={navigateTo}
      onLoggedOut={onLoggedOut}
    />
  }

  return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={onLoggedOut} />
}

export default App
