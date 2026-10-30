import { useEffect, useState } from 'react'
import { useLogout } from './hooks/useLogout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Enrollment from './pages/Enrollment'
import Attendance from './pages/Attendance'
import AttendanceRecalculation from './pages/AttendanceRecalculation'
import MySchedule from './pages/MySchedule'
import ScheduleUploads from './pages/ScheduleUploads'
import ScheduleUploadApprovals from './pages/ScheduleUploadApprovals'
import EmergencyScheduleApprovals from './pages/EmergencyScheduleApprovals'
import Companies from './pages/Companies'
import OrgUnits from './pages/OrgUnits'
import OrgUnitTypes from './pages/OrgUnitTypes'
import OperationalGroups from './pages/OperationalGroups'
import Employees from './pages/Employees'
import Locations from './pages/Locations'
import LocationTypes from './pages/LocationTypes'
import Geofences from './pages/Geofences'
import LeaveManagement from './pages/LeaveManagement'
import Calendar from './pages/Calendar'
import Announcements from './pages/Announcements'
import EmployeeEntitlements from './pages/EmployeeEntitlements'
import LeaveApplication from './pages/LeaveApplication'
import OvertimeApplication from './pages/OvertimeApplication'
import OfficialBusiness from './pages/OfficialBusiness'
import PayrollGroups from './pages/PayrollGroups'
import PayrollCutoffs from './pages/PayrollCutoffs'
import AttendanceDetailReport from './pages/AttendanceDetailReport'
import OrgUnitAttendanceSummaryReport from './pages/OrgUnitAttendanceSummaryReport'
import PayrollResultsReview from './pages/PayrollResultsReview'
import PayrollManagementPage from './features/payroll/presentation/PayrollManagementPage'
import StatutorySchedulesPage from './features/payroll/presentation/StatutorySchedulesPage'
import ThirteenthMonthCalculationPage from './features/payroll/presentation/ThirteenthMonthCalculationPage'
import OffCyclePayrollPage from './features/payroll/presentation/OffCyclePayrollPage'
import PayrollSystemParametersPage from './features/payroll/presentation/PayrollSystemParametersPage'
import CompanyBenefitTypesPage from './features/payroll/presentation/CompanyBenefitTypesPage'
import { PayrollUseCases } from './features/payroll/application/useCases'
import { HttpPayrollRepository } from './features/payroll/infrastructure/HttpPayrollRepository'
import { OffCyclePayrollUseCases } from './features/payroll/application/offCycleUseCases'
import { HttpOffCyclePayrollRepository } from './features/payroll/infrastructure/HttpOffCyclePayrollRepository'
import ScheduleTemplates from './pages/ScheduleTemplates'
import RestDayPatterns from './pages/RestDayPatterns'
import ChangePassword from './pages/ChangePassword'
import type { NavView } from './components/dashboard/TopNav'
import { WorkspaceTabsProvider } from './components/dashboard/WorkspaceTabsContext'
import ErrorBoundary from './components/common/ErrorBoundary'
import { fetchCurrentAuthorization } from './lib/authApi'
import {
  getSelectedDashboardRole,
  hasAnyPermission,
  hasEmployeeRoleCode,
  hasPermission,
} from './types/role'

const payrollUseCases = new PayrollUseCases(new HttpPayrollRepository())
const offCyclePayrollUseCases = new OffCyclePayrollUseCases(new HttpOffCyclePayrollRepository())

const navViews: NavView[] = [
  'dashboard', 'enrollment', 'attendance', 'attendance-detail-report', 'attendance-org-unit-summary', 'attendance-recalculation', 'companies', 'org-units', 'org-unit-types', 'locations', 'location-types',
  'operational-groups', 'geofences', 'employees', 'leave-management', 'calendar', 'announcements', 'employee-entitlements',
  'leave-application', 'payroll-groups', 'payroll-cutoffs', 'payroll-compensation', 'payroll-earning-rules',
  'payroll-management', 'payroll-gross', 'payroll-benefits', 'payroll-deductions', 'payroll-loans', 'payroll-compensation', 'payroll-earning-rules', 'company-benefit-types', 'company-deduction-types', 'payroll-statutory', 'payroll-thirteenth-month', 'payroll-off-cycle', 'payroll-system-parameters', 'payroll-review', 'schedule-templates', 'rest-day-patterns',
  'overtime-application', 'official-business', 'change-password', 'my-schedule', 'schedule-uploads',
  'schedule-upload-approvals',
  'emergency-schedule-approvals',
]

// Every open tab stays mounted (and keeps polling), so cap them to bound memory use.
const MAX_OPEN_TABS = 8

function limitOpenTabs(tabs: NavView[], activeView: NavView): NavView[] {
  const next = [...tabs]
  while (next.length > MAX_OPEN_TABS) {
    const evictIndex = next.findIndex((tab) => tab !== 'dashboard' && tab !== activeView)
    if (evictIndex === -1) break
    next.splice(evictIndex, 1)
  }
  return next
}

function getStoredView(): NavView {
  const storedView = sessionStorage.getItem('active_view')
  return navViews.includes(storedView as NavView) ? storedView as NavView : 'dashboard'
}

function getStoredTabs(): NavView[] {
  const storedTabs = sessionStorage.getItem('open_views')
  if (storedTabs) {
    try {
      const parsedTabs: unknown = JSON.parse(storedTabs)
      if (Array.isArray(parsedTabs)) {
        const validTabs = parsedTabs.filter(
          (tab): tab is NavView => typeof tab === 'string' && navViews.includes(tab as NavView),
        )
        const activeView = getStoredView()
        const restoredTabs: NavView[] = [
          'dashboard',
          ...validTabs.filter((tab) => tab !== 'dashboard' && tab !== activeView),
          ...(activeView === 'dashboard' ? [] : [activeView]),
        ]
        return limitOpenTabs(restoredTabs, activeView)
      }
    } catch {
      sessionStorage.removeItem('open_views')
    }
  }
  return (['dashboard', getStoredView()] as NavView[]).filter(
    (tab, index, tabs) => tabs.indexOf(tab) === index,
  )
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(localStorage.getItem('access_token')))
  const [isAuthorizationLoaded, setIsAuthorizationLoaded] = useState(
    () => !Boolean(localStorage.getItem('access_token')),
  )
  const [employeeName, setEmployeeName] = useState(() => localStorage.getItem('employee_name') ?? '')
  const [view, setView] = useState<NavView>(getStoredView)
  const [openViews, setOpenViews] = useState<NavView[]>(getStoredTabs)
  const [authorizationError, setAuthorizationError] = useState(false)
  const [authorizationRefreshKey, setAuthorizationRefreshKey] = useState(0)
  const { logout } = useLogout({
    onLoggedOut: () => {
      sessionStorage.removeItem('active_view')
      sessionStorage.removeItem('open_views')
      setOpenViews(['dashboard'])
      setView('dashboard')
      setEmployeeName('')
      setIsAuthenticated(false)
    },
  })

  useEffect(() => {
    if (!isAuthenticated) {
      setIsAuthorizationLoaded(true)
      return
    }
    let isCurrent = true
    setAuthorizationError(false)
    fetchCurrentAuthorization()
      .then((authorization) => {
        if (!isCurrent) return
        localStorage.setItem('role_codes', JSON.stringify(authorization.role_codes))
        localStorage.setItem('permission_codes', JSON.stringify(authorization.permission_codes))
        if (authorization.employee_code) {
          localStorage.setItem('employee_code', authorization.employee_code)
        } else {
          localStorage.removeItem('employee_code')
        }
        setIsAuthorizationLoaded(true)
      })
      .catch(() => {
        if (!isCurrent) return
        localStorage.removeItem('permission_codes')
        setView('dashboard')
        setOpenViews(['dashboard'])
        sessionStorage.setItem('open_views', JSON.stringify(['dashboard']))
        sessionStorage.setItem('active_view', 'dashboard')
        setAuthorizationError(true)
        setIsAuthorizationLoaded(true)
      })
    return () => {
      isCurrent = false
    }
  }, [authorizationRefreshKey, isAuthenticated])

  function navigateTo(nextView: NavView) {
    setOpenViews((current) => {
      const next = current.includes(nextView) ? current : limitOpenTabs([...current, nextView], nextView)
      sessionStorage.setItem('open_views', JSON.stringify(next))
      return next
    })
    sessionStorage.setItem('active_view', nextView)
    setView(nextView)
  }

  function selectTab(nextView: NavView) {
    sessionStorage.setItem('active_view', nextView)
    setView(nextView)
  }

  function closeTab(closedView: NavView) {
    if (closedView === 'dashboard') return
    const closedIndex = openViews.indexOf(closedView)
    const remaining = openViews.filter((openView) => openView !== closedView)
    const nextView = view === closedView
      ? remaining[Math.max(0, closedIndex - 1)] ?? 'dashboard'
      : view
    const nextTabs: NavView[] = remaining.length ? remaining : ['dashboard']
    setOpenViews(nextTabs)
    sessionStorage.setItem('open_views', JSON.stringify(nextTabs))
    if (view === closedView) {
      setView(nextView)
      sessionStorage.setItem('active_view', nextView)
    }
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

  if (!isAuthorizationLoaded) return null

  if (authorizationError) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-bold text-slate-900">Access permissions unavailable</h1>
          <p role="alert" className="mt-2 text-sm text-slate-600">
            We couldn&apos;t load your current access permissions. Retry, or sign in again.
          </p>
          <div className="mt-5 flex gap-3">
            <button
              type="button"
              onClick={() => {
                setAuthorizationError(false)
                setIsAuthorizationLoaded(false)
                setAuthorizationRefreshKey((current) => current + 1)
              }}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={logout}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
            >
              Sign out
            </button>
          </div>
        </section>
      </main>
    )
  }

  function renderView(currentView: NavView) {
    const view = currentView
    const requiredPermissionByView: Partial<Record<NavView, string | string[]>> = {
      attendance: ['attendance.read_own', 'attendance.read_team', 'attendance.read_org'],
      'attendance-recalculation': ['attendance.read_own', 'attendance.read_team', 'attendance.read_org'],
      'attendance-detail-report': ['attendance.read_own', 'attendance.read_team', 'attendance.read_org', 'payroll.manage'],
      'attendance-org-unit-summary': 'payroll.manage',
      'payroll-review': ['attendance.read_own', 'attendance.read_team', 'attendance.read_org', 'payroll.manage'],
      companies: 'company.setup',
      'org-units': 'company.setup',
      'org-unit-types': 'company.setup',
      'operational-groups': 'company.setup',
      locations: 'company.setup',
      'location-types': 'company.setup',
      geofences: 'company.setup',
      employees: ['employees.read', 'employees.read_team'],
      'payroll-groups': 'payroll.manage',
      'payroll-cutoffs': 'payroll.manage',
      'payroll-compensation': 'payroll.manage',
      'payroll-earning-rules': 'payroll.manage',
      'payroll-gross': 'payroll.manage',
      'payroll-benefits': 'payroll.manage',
      'payroll-deductions': 'payroll.manage',
      'payroll-loans': 'payroll.manage',
      'payroll-management': 'payroll.manage',
      'company-benefit-types': 'payroll.manage',
      'company-deduction-types': 'payroll.manage',
      'payroll-statutory': 'payroll.company_parameters.manage',
      'payroll-thirteenth-month': 'payroll.manage',
      'payroll-off-cycle': ['payroll.manage', 'payroll.approve'],
      'payroll-system-parameters': 'payroll.company_parameters.manage',
      'schedule-templates': 'schedule.manage',
      'rest-day-patterns': 'schedule.manage',
      'my-schedule': 'schedule.read_own',
      'schedule-uploads': 'schedule.upload_team',
      'schedule-upload-approvals': 'schedule.approve',
      'emergency-schedule-approvals': 'schedule.approve_emergency',
      'leave-management': 'leave.manage',
      calendar: 'leave.manage',
      announcements: 'system.manage',
      'employee-entitlements': 'leave.manage',
      'leave-application': 'leave.submit',
      'overtime-application': 'overtime.submit_own',
      'official-business': 'official_business.submit_own',
    }
    const requiredPermission = requiredPermissionByView[view]
    const hasRequiredPermission = typeof requiredPermission === 'string'
      ? hasPermission(requiredPermission)
      : requiredPermission
        ? hasAnyPermission(requiredPermission)
        : true
    if (!hasRequiredPermission) {
      return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'change-password') {
      return <ChangePassword employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'enrollment') {
      return <Enrollment employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'attendance') {
      return <Attendance employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'attendance-detail-report') {
      return (
        <AttendanceDetailReport
          employeeName={employeeName}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'attendance-org-unit-summary') {
      return (
        <OrgUnitAttendanceSummaryReport
          employeeName={employeeName}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'attendance-recalculation') {
      return (
        <AttendanceRecalculation
          employeeName={employeeName}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'my-schedule') {
      return <MySchedule employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'schedule-uploads') {
      return <ScheduleUploads employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'schedule-upload-approvals') {
      return <ScheduleUploadApprovals employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'emergency-schedule-approvals') {
      return <EmergencyScheduleApprovals employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'companies') {
      return <Companies employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'org-units') {
      return <OrgUnits employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'org-unit-types') {
      return <OrgUnitTypes employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }
    if (view === 'operational-groups') {
      return <OperationalGroups employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'locations') {
      return <Locations employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'location-types') {
      return <LocationTypes employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'geofences') {
      return <Geofences employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'employees') {
      return <Employees employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'leave-management' || view === 'employee-entitlements') {
      if (view === 'leave-management') {
        return <LeaveManagement employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
      }
      return <EmployeeEntitlements employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'calendar') {
      return <Calendar employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'announcements') {
      return <Announcements employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'payroll-groups') {
      return <PayrollGroups employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'payroll-cutoffs') {
      return <PayrollCutoffs employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'payroll-statutory') {
      return (
        <StatutorySchedulesPage
          employeeName={employeeName}
          useCases={payrollUseCases}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'payroll-thirteenth-month') {
      return (
        <ThirteenthMonthCalculationPage
          employeeName={employeeName}
          useCases={payrollUseCases}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'payroll-off-cycle') {
      return (
        <OffCyclePayrollPage
          employeeName={employeeName}
          payrollUseCases={payrollUseCases}
          offCycleUseCases={offCyclePayrollUseCases}
          canManage={hasPermission('payroll.manage')}
          canApprove={hasPermission('payroll.approve')}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'payroll-system-parameters') {
      return (
        <PayrollSystemParametersPage
          employeeName={employeeName}
          useCases={payrollUseCases}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'company-benefit-types' || view === 'company-deduction-types') {
      return (
        <CompanyBenefitTypesPage
          key={view}
          employeeName={employeeName}
          useCases={payrollUseCases}
          setupType={view === 'company-benefit-types' ? 'benefits' : 'deductions'}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'payroll-management') {
      return (
        <PayrollManagementPage
          employeeName={employeeName}
          activeView="payroll-compensation"
          useCases={payrollUseCases}
          canApprovePayroll={hasPermission('payroll.approve')}
          canUnlockPayroll={hasPermission('payroll.approve')}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'payroll-compensation' || view === 'payroll-earning-rules' || view === 'payroll-gross' || view === 'payroll-benefits' || view === 'payroll-deductions' || view === 'payroll-loans') {
      return (
        <PayrollManagementPage
          employeeName={employeeName}
          activeView={view}
          useCases={payrollUseCases}
          canApprovePayroll={hasPermission('payroll.approve')}
          canUnlockPayroll={hasPermission('payroll.approve')}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'payroll-review') {
      return <PayrollResultsReview employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'schedule-templates') {
      return <ScheduleTemplates employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'rest-day-patterns') {
      return <RestDayPatterns employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
    }

    if (view === 'leave-application') {
      if (getSelectedDashboardRole() !== 'employee') {
        return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
      }

      return (
        <LeaveApplication
          employeeName={employeeName}
          previewOnly={!hasEmployeeRoleCode()}
          onNavigate={navigateTo}
          onLoggedOut={logout}
        />
      )
    }

    if (view === 'overtime-application') {
      if (getSelectedDashboardRole() !== 'employee') {
        return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
      }
      return <OvertimeApplication
        employeeName={employeeName}
        previewOnly={!hasEmployeeRoleCode()}
        onNavigate={navigateTo}
        onLoggedOut={logout}
      />
    }

    if (view === 'official-business') {
      if (getSelectedDashboardRole() !== 'employee') {
        return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
      }
      return <OfficialBusiness
        employeeName={employeeName}
        previewOnly={!hasEmployeeRoleCode()}
        onNavigate={navigateTo}
        onLoggedOut={logout}
      />
    }

    return <Dashboard employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
}

  return (
    <WorkspaceTabsProvider
      value={{
        views: openViews,
        activeView: view,
        onSelect: selectTab,
        onClose: closeTab,
      }}
    >
      {openViews.map((openView) => (
        <div key={openView} hidden={openView !== view}>
          <ErrorBoundary label={openView}>
            {renderView(openView)}
          </ErrorBoundary>
        </div>
      ))}
    </WorkspaceTabsProvider>
  )
}

export default App
