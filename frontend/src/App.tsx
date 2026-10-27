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
import Employees from './pages/Employees'
import Locations from './pages/Locations'
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
  'dashboard', 'enrollment', 'attendance', 'attendance-detail-report', 'attendance-recalculation', 'companies', 'org-units', 'locations',
  'geofences', 'employees', 'leave-management', 'calendar', 'announcements', 'employee-entitlements',
  'leave-application', 'payroll-groups', 'payroll-cutoffs', 'payroll-compensation', 'payroll-earning-rules',
  'payroll-management', 'payroll-gross', 'payroll-benefits', 'payroll-deductions', 'payroll-loans', 'payroll-compensation', 'payroll-earning-rules', 'company-benefit-types', 'company-deduction-types', 'payroll-statutory', 'payroll-thirteenth-month', 'payroll-off-cycle', 'payroll-system-parameters', 'payroll-review', 'schedule-templates', 'rest-day-patterns',
  'overtime-application', 'official-business', 'change-password', 'my-schedule', 'schedule-uploads',
  'schedule-upload-approvals',
  'emergency-schedule-approvals',
]

function getStoredView(): NavView {
  const storedView = sessionStorage.getItem('active_view')
  return navViews.includes(storedView as NavView) ? storedView as NavView : 'dashboard'
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(localStorage.getItem('access_token')))
  const [isAuthorizationLoaded, setIsAuthorizationLoaded] = useState(
    () => !Boolean(localStorage.getItem('access_token')),
  )
  const [employeeName, setEmployeeName] = useState(() => localStorage.getItem('employee_name') ?? '')
  const [view, setView] = useState<NavView>(getStoredView)
  const [authorizationError, setAuthorizationError] = useState(false)
  const [authorizationRefreshKey, setAuthorizationRefreshKey] = useState(0)
  const { logout } = useLogout({
    onLoggedOut: () => {
      sessionStorage.removeItem('active_view')
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
        sessionStorage.setItem('active_view', 'dashboard')
        setAuthorizationError(true)
        setIsAuthorizationLoaded(true)
      })
    return () => {
      isCurrent = false
    }
  }, [authorizationRefreshKey, isAuthenticated])

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

  const requiredPermissionByView: Partial<Record<NavView, string | string[]>> = {
    attendance: ['attendance.read_own', 'attendance.read_team', 'attendance.read_org'],
    'attendance-recalculation': ['attendance.read_own', 'attendance.read_team', 'attendance.read_org'],
    'attendance-detail-report': ['attendance.read_own', 'attendance.read_team', 'attendance.read_org', 'payroll.manage'],
    'payroll-review': ['attendance.read_own', 'attendance.read_team', 'attendance.read_org', 'payroll.manage'],
    companies: 'company.setup',
    'org-units': 'company.setup',
    locations: 'company.setup',
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

  if (view === 'locations') {
    return <Locations employeeName={employeeName} onNavigate={navigateTo} onLoggedOut={logout} />
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

export default App
