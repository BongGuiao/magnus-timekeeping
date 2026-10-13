import { useEffect, useState } from 'react'
import { mockDashboardData } from '../data/mockDashboard'
import { useLogout } from '../hooks/useLogout'
import {
  approveSupervisorInvalidAttendance,
  decideOvertimeApplication,
  fetchPendingOvertimeApplications,
  fetchSupervisorInvalidAttendance,
  fetchAdminDashboardSnapshot,
  fetchRecentAttendanceSnapshot,
  type AdminAttendanceException,
  type AdminDashboardSnapshot,
  type OvertimeApplication,
  type SupervisorInvalidAttendance,
} from '../lib/attendanceApi'
import { fetchPendingDeviceSnapshot, type DeviceRecord, updateDeviceRegistration } from '../lib/deviceApi'
import {
  decideSupervisorPendingLeave,
  fetchLeaveDashboardSnapshot,
  fetchSupervisorPendingLeaveCount,
  fetchSupervisorPendingLeaves,
  formatLeaveBalance,
} from '../lib/leaveApi'
import type { SupervisorPendingLeave } from '../lib/leaveApi'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import HeroBanner from '../components/dashboard/HeroBanner'
import StatCard from '../components/dashboard/StatCard'
import LeaveBalanceGrid from '../components/dashboard/LeaveBalanceGrid'
import WorkHoursCard from '../components/dashboard/WorkHoursCard'
import RecentAttendanceTable from '../components/dashboard/RecentAttendanceTable'
import OvertimeApprovalsPanel from '../components/dashboard/OvertimeApprovalsPanel'
import OfficialBusinessApprovalsPanel from '../components/dashboard/OfficialBusinessApprovalsPanel'
import {
  AnnouncementsCard,
  HolidaysCard,
  LeaveRequestsCard,
  SupervisorPendingLeavesCard,
} from '../components/dashboard/SideCards'
import { getSelectedDashboardRole, normalizeDashboardRole, type DashboardRole } from '../types/role'
import type {
  AttendanceLogEntry,
  LeaveBalance,
  LeaveRequest,
} from '../types/dashboard'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

type DeviceReviewStatus = Exclude<DeviceRecord['registration_status'], 'PENDING'>
type AdminDashboardPanel = 'no-login' | 'no-logout' | 'pending-leaves' | 'weekly-hours' | 'invalid-attendance'

function formatWeeklyHours(hours: number): string {
  const totalMinutes = Math.round(hours * 60)
  return `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m`
}

function getAdminPanelForMetric(label: string): AdminDashboardPanel | null {
  switch (label) {
    case 'No Login':
      return 'no-login'
    case 'No Logout':
      return 'no-logout'
    case 'Pending Leave':
      return 'pending-leaves'
    case 'Hours This Week':
      return 'weekly-hours'
    case 'Invalid Attendance':
      return 'invalid-attendance'
    default:
      return null
  }
}

interface DeviceReviewDraft {
  status: DeviceReviewStatus | ''
  reason: string
}

export default function Dashboard({ employeeName, onNavigate, onLoggedOut }: Props) {
  const data = mockDashboardData
  const { logout } = useLogout({ onLoggedOut })
  const [role, setRole] = useState<DashboardRole>(getSelectedDashboardRole)
  const isAdmin = normalizeDashboardRole(localStorage.getItem('role')) === 'administrator'
  const [pendingDevices, setPendingDevices] = useState<DeviceRecord[]>([])
  const [isLoadingDevices, setIsLoadingDevices] = useState(isAdmin)
  const [hasLoadedDevices, setHasLoadedDevices] = useState(false)
  const [snapshotRefreshedAt, setSnapshotRefreshedAt] = useState<string | null>(null)
  const [isPendingListOpen, setIsPendingListOpen] = useState(false)
  const [savingDeviceId, setSavingDeviceId] = useState<string | null>(null)
  const [deviceReviewDrafts, setDeviceReviewDrafts] = useState<Record<string, DeviceReviewDraft>>({})
  const [deviceError, setDeviceError] = useState<string | null>(null)
  const [adminDashboardSnapshot, setAdminDashboardSnapshot] = useState<AdminDashboardSnapshot | null>(null)
  const [isLoadingAdminDashboard, setIsLoadingAdminDashboard] = useState(isAdmin)
  const [adminDashboardError, setAdminDashboardError] = useState<string | null>(null)
  const [adminPanel, setAdminPanel] = useState<AdminDashboardPanel | null>(null)
  const [recentAttendance, setRecentAttendance] = useState<AttendanceLogEntry[]>([])
  const [weeklyHoursWorked, setWeeklyHoursWorked] = useState<number | null>(null)
  const [missedClockInsThisMonth, setMissedClockInsThisMonth] = useState<number | null>(null)
  const [attendanceSnapshotRefreshedAt, setAttendanceSnapshotRefreshedAt] = useState<string | null>(null)
  const [isLoadingRecentAttendance, setIsLoadingRecentAttendance] = useState(false)
  const [recentAttendanceError, setRecentAttendanceError] = useState<string | null>(null)
  const [leaveBalances, setLeaveBalances] = useState<LeaveBalance[]>([])
  const [leaveRequests, setLeaveRequests] = useState<LeaveRequest[]>([])
  const [isLoadingLeaveDashboard, setIsLoadingLeaveDashboard] = useState(false)
  const [leaveDashboardError, setLeaveDashboardError] = useState<string | null>(null)
  const [leaveDashboardRefreshedAt, setLeaveDashboardRefreshedAt] = useState<string | null>(null)
  const [supervisorPendingLeaves, setSupervisorPendingLeaves] = useState<SupervisorPendingLeave[]>([])
  const [supervisorPendingLeaveCount, setSupervisorPendingLeaveCount] = useState(0)
  const [isLoadingSupervisorLeaves, setIsLoadingSupervisorLeaves] = useState(false)
  const [supervisorLeavesError, setSupervisorLeavesError] = useState<string | null>(null)
  const [isSupervisorLeavePanelOpen, setIsSupervisorLeavePanelOpen] = useState(false)
  const [supervisorLeaveDecisions, setSupervisorLeaveDecisions] = useState<Record<string, 'APPROVED' | 'REJECTED' | ''>>({})
  const [savingSupervisorLeaveId, setSavingSupervisorLeaveId] = useState<string | null>(null)
  const [supervisorInvalidAttendance, setSupervisorInvalidAttendance] = useState<SupervisorInvalidAttendance[]>([])
  const [isLoadingInvalidAttendance, setIsLoadingInvalidAttendance] = useState(false)
  const [invalidAttendanceError, setInvalidAttendanceError] = useState<string | null>(null)
  const [isInvalidAttendancePanelOpen, setIsInvalidAttendancePanelOpen] = useState(false)
  const [savingInvalidAttendanceId, setSavingInvalidAttendanceId] = useState<string | null>(null)
  const [pendingOvertimeRequests, setPendingOvertimeRequests] = useState<OvertimeApplication[]>([])
  const [isLoadingOvertimeRequests, setIsLoadingOvertimeRequests] = useState(false)
  const [overtimeRequestsError, setOvertimeRequestsError] = useState<string | null>(null)
  const [isOvertimeApprovalPanelOpen, setIsOvertimeApprovalPanelOpen] = useState(false)
  const [isOfficialBusinessPanelOpen, setIsOfficialBusinessPanelOpen] = useState(false)
  const [pendingOfficialBusinessCount, setPendingOfficialBusinessCount] = useState<number | null>(null)
  const [savingOvertimeRequestId, setSavingOvertimeRequestId] = useState<string | null>(null)
  const showEmployeeAttendance = role === 'employee'

  useEffect(() => {
    const updateRole = () => setRole(getSelectedDashboardRole())
    window.addEventListener('dashboard-role-change', updateRole)
    return () => window.removeEventListener('dashboard-role-change', updateRole)
  }, [])

  useEffect(() => {
    if (!showEmployeeAttendance) return

    let isCurrent = true
    const refreshRecentAttendance = async (showLoading: boolean) => {
      if (showLoading) setIsLoadingRecentAttendance(true)
      try {
        const snapshot = await fetchRecentAttendanceSnapshot()
        if (!isCurrent) return
        setRecentAttendance(snapshot.entries)
        setWeeklyHoursWorked(snapshot.weeklyHoursWorked)
        setMissedClockInsThisMonth(snapshot.missedClockInsThisMonth)
        setAttendanceSnapshotRefreshedAt(snapshot.refreshedAt)
        setRecentAttendanceError(null)
      } catch (error) {
        if (!isCurrent) return
        setRecentAttendanceError(
          error instanceof Error ? error.message : 'Could not load recent attendance.',
        )
      } finally {
        if (isCurrent && showLoading) setIsLoadingRecentAttendance(false)
      }
    }

    void refreshRecentAttendance(true)
    const refreshTimer = window.setInterval(() => {
      void refreshRecentAttendance(false)
    }, 5 * 60 * 1000)

    return () => {
      isCurrent = false
      window.clearInterval(refreshTimer)
    }
  }, [showEmployeeAttendance])

  useEffect(() => {
    if (role !== 'employee') return

    let isCurrent = true
    const refreshLeaveDashboard = async (showLoading: boolean) => {
      if (showLoading) setIsLoadingLeaveDashboard(true)
      try {
        const snapshot = await fetchLeaveDashboardSnapshot()
        if (!isCurrent) return
        setLeaveBalances(snapshot.balances.map((balance) => ({
          type: balance.type,
          label: balance.label,
          unitType: balance.unit_type,
          allotted: balance.allotted_minutes,
          used: balance.used_minutes,
          available: balance.available_minutes,
        })))
        setLeaveRequests(snapshot.applications.map((application) => ({
          id: application.id,
          type: application.type,
          startDate: new Date(application.start_at).toLocaleDateString(),
          endDate: new Date(application.end_at).toLocaleDateString(),
          status: application.status,
        })))
        setLeaveDashboardRefreshedAt(snapshot.refreshed_at)
        setLeaveDashboardError(null)
      } catch (error) {
        if (!isCurrent) return
        setLeaveDashboardError(error instanceof Error ? error.message : 'Could not load leave dashboard data.')
      } finally {
        if (isCurrent && showLoading) setIsLoadingLeaveDashboard(false)
      }
    }

    void refreshLeaveDashboard(true)
    const refreshTimer = window.setInterval(() => {
      void refreshLeaveDashboard(false)
    }, 30 * 1000)
    const handleFocus = () => void refreshLeaveDashboard(false)
    window.addEventListener('focus', handleFocus)

    return () => {
      isCurrent = false
      window.clearInterval(refreshTimer)
      window.removeEventListener('focus', handleFocus)
    }
  }, [role])

  useEffect(() => {
    if (role !== 'supervisor' && role !== 'manager' && !(isAdmin && role === 'administrator')) return

    let isCurrent = true
    const refreshPendingLeaveCount = async () => {
      try {
        const count = await fetchSupervisorPendingLeaveCount()
        if (!isCurrent) return
        setSupervisorPendingLeaveCount(count)
        setSupervisorLeavesError(null)
      } catch (error) {
        if (!isCurrent) return
        setSupervisorLeavesError(
          error instanceof Error ? error.message : 'Could not load pending team leave applications.',
        )
      }
    }

    const refreshInvalidAttendance = async (showLoading = false) => {
      if (showLoading) setIsLoadingInvalidAttendance(true)
      try {
        const records = await fetchSupervisorInvalidAttendance()
        if (!isCurrent) return
        setSupervisorInvalidAttendance(records)
        setInvalidAttendanceError(null)
      } catch (error) {
        if (!isCurrent) return
        setInvalidAttendanceError(
          error instanceof Error ? error.message : 'Could not load invalid attendance for your team.',
        )
      } finally {
        if (isCurrent && showLoading) setIsLoadingInvalidAttendance(false)
      }
    }

    const refreshOvertimeRequests = async (showLoading = false) => {
      if (showLoading) setIsLoadingOvertimeRequests(true)
      try {
        const requests = await fetchPendingOvertimeApplications()
        if (!isCurrent) return
        setPendingOvertimeRequests(requests)
        setOvertimeRequestsError(null)
      } catch (error) {
        if (!isCurrent) return
        setOvertimeRequestsError(
          error instanceof Error ? error.message : 'Could not load pending overtime applications.',
        )
      } finally {
        if (isCurrent && showLoading) setIsLoadingOvertimeRequests(false)
      }
    }

    void refreshPendingLeaveCount()
    void refreshInvalidAttendance(true)
    void refreshOvertimeRequests(true)
    const refreshTimer = window.setInterval(() => {
      void refreshPendingLeaveCount()
      void refreshInvalidAttendance()
      void refreshOvertimeRequests()
    }, 30 * 1000)
    const handleFocus = () => {
      void refreshPendingLeaveCount()
      void refreshInvalidAttendance()
      void refreshOvertimeRequests()
    }
    window.addEventListener('focus', handleFocus)
    return () => {
      isCurrent = false
      window.clearInterval(refreshTimer)
      window.removeEventListener('focus', handleFocus)
    }
  }, [isAdmin, role])

  async function toggleSupervisorLeavePanel() {
    const shouldOpen = !isSupervisorLeavePanelOpen
    setIsSupervisorLeavePanelOpen(shouldOpen)
    if (!shouldOpen) return

    setIsLoadingSupervisorLeaves(true)
    setSupervisorLeavesError(null)
    try {
      const leaves = await fetchSupervisorPendingLeaves()
      setSupervisorPendingLeaves(leaves)
      setSupervisorPendingLeaveCount(leaves.length)
    } catch (error) {
      setSupervisorLeavesError(
        error instanceof Error ? error.message : 'Could not load pending team leave applications.',
      )
    } finally {
      setIsLoadingSupervisorLeaves(false)
    }
  }

  async function toggleInvalidAttendancePanel() {
    const shouldOpen = !isInvalidAttendancePanelOpen
    setIsInvalidAttendancePanelOpen(shouldOpen)
    if (!shouldOpen) return

    setIsLoadingInvalidAttendance(true)
    setInvalidAttendanceError(null)
    try {
      setSupervisorInvalidAttendance(await fetchSupervisorInvalidAttendance())
    } catch (error) {
      setInvalidAttendanceError(
        error instanceof Error ? error.message : 'Could not load invalid attendance for your team.',
      )
    } finally {
      setIsLoadingInvalidAttendance(false)
    }
  }

  async function approveInvalidAttendance(attendanceId: string) {
    setSavingInvalidAttendanceId(attendanceId)
    setInvalidAttendanceError(null)
    try {
      await approveSupervisorInvalidAttendance(attendanceId)
      setSupervisorInvalidAttendance((current) => current.filter((record) => record.id !== attendanceId))
    } catch (error) {
      setInvalidAttendanceError(
        error instanceof Error ? error.message : 'Could not approve this attendance record.',
      )
    } finally {
      setSavingInvalidAttendanceId(null)
    }
  }

  async function decideTeamOvertimeRequest(
    applicationId: string,
    decision: 'APPROVED' | 'REJECTED',
    approvedMinutes: number,
  ) {
    setSavingOvertimeRequestId(applicationId)
    setOvertimeRequestsError(null)
    try {
      await decideOvertimeApplication(applicationId, decision, approvedMinutes)
      setPendingOvertimeRequests((current) => current.filter((request) => request.id !== applicationId))
    } catch (error) {
      setOvertimeRequestsError(
        error instanceof Error ? error.message : 'Could not save the overtime application decision.',
      )
    } finally {
      setSavingOvertimeRequestId(null)
    }
  }

  async function saveSupervisorLeaveDecision(applicationId: string) {
    const decision = supervisorLeaveDecisions[applicationId]
    if (!decision) return

    setSavingSupervisorLeaveId(applicationId)
    setSupervisorLeavesError(null)
    try {
      await decideSupervisorPendingLeave(applicationId, decision)
      setSupervisorPendingLeaves((current) => current.filter((leave) => leave.id !== applicationId))
      setSupervisorPendingLeaveCount((current) => Math.max(0, current - 1))
      setSupervisorLeaveDecisions((current) => {
        const { [applicationId]: _savedDecision, ...remaining } = current
        return remaining
      })
    } catch (error) {
      setSupervisorLeavesError(
        error instanceof Error ? error.message : 'Could not save the leave decision.',
      )
    } finally {
      setSavingSupervisorLeaveId(null)
    }
  }

  const dashboardLeaveRequests = role === 'employee' ? leaveRequests : data.leaveRequests
  const dashboardLeaveBalances = role === 'employee' ? leaveBalances : data.leaveBalances

  useEffect(() => {
    if (!isAdmin) return

    let isCurrent = true
    const refreshPendingDevices = async (showLoading: boolean) => {
      if (showLoading) setIsLoadingDevices(true)
      try {
        const snapshot = await fetchPendingDeviceSnapshot()
        if (!isCurrent) return
        setPendingDevices(snapshot.devices)
        setSnapshotRefreshedAt(snapshot.refreshed_at)
        setHasLoadedDevices(true)
        setDeviceError(null)
      } catch (error) {
        if (!isCurrent) return
        setDeviceError(error instanceof Error ? error.message : 'Could not load pending device registrations.')
      } finally {
        if (isCurrent && showLoading) setIsLoadingDevices(false)
      }
    }

    void refreshPendingDevices(true)
    const refreshTimer = window.setInterval(() => {
      void refreshPendingDevices(false)
    }, 5 * 60 * 1000)

    return () => {
      isCurrent = false
      window.clearInterval(refreshTimer)
    }
  }, [isAdmin])

  useEffect(() => {
    if (!isAdmin) return

    let isCurrent = true
    const refreshAdminDashboard = async (showLoading: boolean) => {
      if (showLoading) setIsLoadingAdminDashboard(true)
      try {
        const snapshot = await fetchAdminDashboardSnapshot()
        if (!isCurrent) return
        setAdminDashboardSnapshot(snapshot)
        setAdminDashboardError(null)
      } catch (error) {
        if (!isCurrent) return
        setAdminDashboardError(
          error instanceof Error ? error.message : 'Could not load administrator dashboard details.',
        )
      } finally {
        if (isCurrent && showLoading) setIsLoadingAdminDashboard(false)
      }
    }

    void refreshAdminDashboard(true)
    const refreshTimer = window.setInterval(() => void refreshAdminDashboard(false), 5 * 60 * 1000)
    const handleFocus = () => void refreshAdminDashboard(false)
    window.addEventListener('focus', handleFocus)
    return () => {
      isCurrent = false
      window.clearInterval(refreshTimer)
      window.removeEventListener('focus', handleFocus)
    }
  }, [isAdmin])

  function toggleAdminPanel(panel: AdminDashboardPanel) {
    setAdminPanel((current) => current === panel ? null : panel)
  }

  function updateDeviceDraft(deviceId: string, changes: Partial<DeviceReviewDraft>) {
    setDeviceReviewDrafts((current) => {
      const draft = current[deviceId] ?? { status: '', reason: '' }
      return {
        ...current,
        [deviceId]: { ...draft, ...changes },
      }
    })
  }

  async function saveDeviceReview(deviceId: string) {
    const draft = deviceReviewDrafts[deviceId]
    if (!draft?.status || (draft.status === 'REVOKED' && !draft.reason.trim())) return

    setSavingDeviceId(deviceId)
    setDeviceError(null)
    try {
      await updateDeviceRegistration(deviceId, draft.status, draft.reason.trim())
      setPendingDevices((current) => current.filter((device) => device.id !== deviceId))
      setDeviceReviewDrafts((current) => {
        const { [deviceId]: _savedDraft, ...remaining } = current
        return remaining
      })
    } catch (error) {
      setDeviceError(error instanceof Error ? error.message : 'Could not save this device review.')
    } finally {
      setSavingDeviceId(null)
    }
  }

  const adminWeeklyMinutesTotal = adminDashboardSnapshot?.weekly_hours.reduce(
    (total, employee) => total + employee.minutes_worked,
    0,
  )
  const recentNoLogoutCount = recentAttendance.filter((entry) => entry.status === 'no-logout').length
  const roleContent: Record<DashboardRole, {
    title: string
    description: string
    metrics: { label: string; value: string | number; hint: string; icon: string; accent: 'indigo' | 'rose' | 'amber' | 'emerald' }[]
  }> = {
    administrator: {
      title: 'Organization Overview',
      description: 'Organization-wide attendance and leave indicators.',
      metrics: [
        { label: 'No Login', value: isLoadingAdminDashboard ? '…' : adminDashboardSnapshot?.no_login.length ?? '—', hint: 'Click to view this month', icon: '🚪', accent: 'rose' },
        { label: 'No Logout', value: isLoadingAdminDashboard ? '…' : adminDashboardSnapshot?.no_logout.length ?? '—', hint: 'Click to view this month', icon: '⏱️', accent: 'amber' },
        { label: 'Pending Leave', value: isLoadingAdminDashboard ? '…' : adminDashboardSnapshot?.pending_leaves.length ?? '—', hint: 'Click to view pending requests', icon: '📋', accent: 'indigo' },
        { label: 'Invalid Attendance', value: isLoadingInvalidAttendance ? '…' : supervisorInvalidAttendance.length, hint: 'Click to review and approve', icon: '⚠️', accent: 'amber' },
        { label: 'Hours This Week', value: isLoadingAdminDashboard ? '…' : adminWeeklyMinutesTotal === undefined ? '—' : formatWeeklyHours(adminWeeklyMinutesTotal / 60), hint: 'Click to view employee hours', icon: '📊', accent: 'emerald' },
      ],
    },
    manager: {
      title: 'Team Overview',
      description: 'Preview team attendance exceptions, leave requests, and work hours.',
      metrics: [
        { label: 'Team No Login', value: data.attendanceExceptions.noLogin, hint: 'Needs follow-up', icon: '🚪', accent: 'rose' },
        { label: 'Team No Logout', value: data.attendanceExceptions.noLogout, hint: 'Needs follow-up', icon: '⏱️', accent: 'amber' },
        { label: 'Leave Requests', value: data.leaveRequests.filter((request) => request.status === 'pending').length, hint: 'Pending approval', icon: '📋', accent: 'indigo' },
        { label: 'Team Hours', value: `${data.workHours.weeklyHours}h`, hint: `Weekly target ${data.workHours.weeklyTarget}h`, icon: '📊', accent: 'emerald' },
      ],
    },
    supervisor: {
      title: 'Shift Overview',
      description: 'Preview shift attendance and the exceptions that need attention.',
      metrics: [
        { label: 'Missing Clock-In', value: data.attendanceExceptions.noLogin, hint: 'Review attendance', icon: '🚪', accent: 'rose' },
        { label: 'Missing Clock-Out', value: data.attendanceExceptions.noLogout, hint: 'Review attendance', icon: '⏱️', accent: 'amber' },
        { label: 'Pending Requests', value: supervisorPendingLeaveCount, hint: 'Click to review team leave', icon: '📋', accent: 'indigo' },
        { label: 'Invalid Attendance', value: isLoadingInvalidAttendance ? '…' : supervisorInvalidAttendance.length, hint: 'Click to review and approve', icon: '⚠️', accent: 'amber' },
        { label: 'Hours This Week', value: `${data.workHours.weeklyHours}h`, hint: 'Shift hours recorded', icon: '📊', accent: 'emerald' },
      ],
    },
    employee: {
      title: 'My Attendance Overview',
      description: 'Your attendance, leave balance, and work-hour summary.',
      metrics: [
        {
          label: 'No Login',
          value: isLoadingRecentAttendance
            ? 'Loading…'
            : recentAttendanceError
              ? 'Unavailable'
              : missedClockInsThisMonth ?? '—',
          hint: 'Missed clock-ins this month',
          icon: '🚪',
          accent: 'rose',
        },
        {
          label: 'No Logout',
          value: isLoadingRecentAttendance || attendanceSnapshotRefreshedAt === null
            ? 'Loading…'
            : recentAttendanceError
              ? 'Unavailable'
              : recentNoLogoutCount,
          hint: 'In recent attendance',
          icon: '⏱️',
          accent: 'amber',
        },
        { label: 'Leave Applications', value: leaveRequests.length, hint: 'Your saved requests', icon: '📋', accent: 'indigo' },
        {
          label: 'Hours This Week',
          value: isLoadingRecentAttendance
            ? 'Loading…'
            : recentAttendanceError
              ? 'Unavailable'
              : weeklyHoursWorked === null
                ? '—'
                : formatWeeklyHours(weeklyHoursWorked),
          hint: `Target ${data.workHours.weeklyTarget}h`,
          icon: '📊',
          accent: 'emerald',
        },
      ],
    },
  }
  const content = roleContent[role]

  return (
    <div className="min-h-screen bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="dashboard" onNavigate={onNavigate} onSignOut={logout} />

      <main className="mx-auto w-[95%] pt-6">
        <HeroBanner employeeFirstName={employeeName.split(' ')[0]} role={role} />
        <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">{role} dashboard</p>
              <h2 className="mt-1 text-xl font-extrabold text-slate-900">{content.title}</h2>
              <p className="mt-1 text-sm text-slate-500">{content.description}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-block w-fit rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-600">
                {isAdmin && role === 'administrator'
                  ? 'Attendance: This month · Hours: This week'
                  : data.attendanceExceptions.periodLabel}
              </span>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {content.metrics.map((metric) => {
              const adminPanelForMetric = getAdminPanelForMetric(metric.label)
              if (role === 'supervisor' && metric.label === 'Pending Requests') {
                return (
                  <button
                    key={metric.label}
                    type="button"
                    aria-expanded={isSupervisorLeavePanelOpen}
                    onClick={() => void toggleSupervisorLeavePanel()}
                    className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-indigo-500 hover:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                  >
                    <div className="flex items-start justify-between">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{metric.label}</p>
                      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-50 text-sm text-indigo-600">{metric.icon}</span>
                    </div>
                    <p className="mt-3 text-2xl font-extrabold text-slate-900">{supervisorPendingLeaveCount}</p>
                    <p className="mt-1 text-xs font-medium text-indigo-600">
                      {isSupervisorLeavePanelOpen ? 'Hide approval list' : metric.hint}
                    </p>
                  </button>
                )
              }

              if (role === 'supervisor' && metric.label === 'Invalid Attendance') {
                return (
                  <button
                    key={metric.label}
                    type="button"
                    aria-expanded={isInvalidAttendancePanelOpen}
                    onClick={() => void toggleInvalidAttendancePanel()}
                    className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-amber-500 hover:border-amber-300 focus:outline-none focus:ring-2 focus:ring-amber-300"
                  >
                    <div className="flex items-start justify-between">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{metric.label}</p>
                      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-50 text-sm text-amber-600">{metric.icon}</span>
                    </div>
                    <p className="mt-3 text-2xl font-extrabold text-slate-900">{metric.value}</p>
                    <p className="mt-1 text-xs font-medium text-amber-700">
                      {isInvalidAttendancePanelOpen ? 'Hide approval list' : metric.hint}
                    </p>
                  </button>
                )
              }

              if (isAdmin && role === 'administrator' && adminPanelForMetric) {
                return (
                  <button
                    key={metric.label}
                    type="button"
                    aria-expanded={adminPanel === adminPanelForMetric}
                    onClick={() => toggleAdminPanel(adminPanelForMetric)}
                    className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-indigo-500 hover:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                  >
                    <div className="flex items-start justify-between">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{metric.label}</p>
                      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-50 text-sm text-indigo-600">{metric.icon}</span>
                    </div>
                    <p className="mt-3 text-2xl font-extrabold text-slate-900">{metric.value}</p>
                    <p className="mt-1 text-xs font-medium text-indigo-600">
                      {adminPanel === adminPanelForMetric ? 'Hide details' : metric.hint}
                    </p>
                  </button>
                )
              }

              return <StatCard key={metric.label} {...metric} />
            })}
            {isAdmin && role !== 'employee' && (
              <button
                type="button"
                aria-expanded={isPendingListOpen}
                onClick={() => setIsPendingListOpen((current) => !current)}
                className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-amber-500 hover:border-amber-300 focus:outline-none focus:ring-2 focus:ring-amber-300"
              >
                <div className="flex items-start justify-between">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Pending Devices</p>
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-50 text-sm text-amber-600">
                    📱
                  </span>
                </div>
                <p className="mt-3 text-2xl font-extrabold text-slate-900">
                  {isLoadingDevices ? '…' : hasLoadedDevices ? pendingDevices.length : '—'}
                </p>
                <p className="mt-1 text-xs font-medium text-amber-600">
                  {isPendingListOpen ? 'Hide review list' : 'Click to review pending devices'}
                </p>
              </button>
            )}
            {(role === 'supervisor' || role === 'manager' || (isAdmin && role === 'administrator')) && (
              <button
                type="button"
                aria-expanded={isOvertimeApprovalPanelOpen}
                onClick={() => setIsOvertimeApprovalPanelOpen((current) => !current)}
                className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-emerald-500 hover:border-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-300"
              >
                <div className="flex items-start justify-between">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Overtime Approvals</p>
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-50 text-sm text-emerald-600">
                    ⏱️
                  </span>
                </div>
                <p className="mt-3 text-2xl font-extrabold text-slate-900">
                  {isLoadingOvertimeRequests ? '…' : pendingOvertimeRequests.length}
                </p>
                <p className="mt-1 text-xs font-medium text-emerald-700">
                  {isOvertimeApprovalPanelOpen ? 'Hide approval list' : 'Review overtime requests'}
                </p>
              </button>
            )}
            {(role === 'supervisor' || role === 'manager' || (isAdmin && role === 'administrator')) && (
              <button
                type="button"
                aria-expanded={isOfficialBusinessPanelOpen}
                onClick={() => setIsOfficialBusinessPanelOpen((current) => !current)}
                className="relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-sky-500 hover:border-sky-300 focus:outline-none focus:ring-2 focus:ring-sky-300"
              >
                <div className="flex items-start justify-between">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Official Business</p>
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-50 text-sm text-sky-600">
                    💼
                  </span>
                </div>
                <p className="mt-3 text-2xl font-extrabold text-slate-900">
                  {pendingOfficialBusinessCount ?? '—'}
                </p>
                <p className="mt-1 text-xs font-medium text-sky-700">
                  {isOfficialBusinessPanelOpen ? 'Hide approval list' : 'Review official business'}
                </p>
              </button>
            )}
          </div>
        </section>

        {(role === 'supervisor' || role === 'manager' || (isAdmin && role === 'administrator')) && isOvertimeApprovalPanelOpen && (
          <OvertimeApprovalsPanel
            requests={pendingOvertimeRequests}
            isLoading={isLoadingOvertimeRequests}
            error={overtimeRequestsError}
            savingId={savingOvertimeRequestId}
            onDecision={decideTeamOvertimeRequest}
          />
        )}

        {(role === 'supervisor' || role === 'manager' || (isAdmin && role === 'administrator')) && isOfficialBusinessPanelOpen && (
          <OfficialBusinessApprovalsPanel onPendingCountChange={setPendingOfficialBusinessCount} />
        )}

        {isAdmin && role === 'administrator' && adminPanel !== null && (
          <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">
                  {adminPanel === 'no-login'
                    ? 'Employees with no login'
                    : adminPanel === 'no-logout'
                      ? 'Employees with no logout'
                      : adminPanel === 'pending-leaves'
                        ? 'Pending leave requests'
                        : 'Employee hours this week'}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  {adminPanel === 'invalid-attendance'
                    ? 'Invalid attendance awaiting supervisor review.'
                    : adminPanel === 'no-login' || adminPanel === 'no-logout'
                    ? 'Attendance exceptions recorded this month.'
                    : adminPanel === 'pending-leaves'
                      ? 'Leave requests awaiting review.'
                      : 'Recorded hours from Monday through today.'}
                </p>
                {adminDashboardSnapshot && (
                  <p className="mt-1 text-xs text-slate-400">
                    Snapshot refreshed {new Date(adminDashboardSnapshot.refreshed_at).toLocaleString()}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setAdminPanel(null)}
                className="w-fit rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
              >
                Close
              </button>
            </div>

            {adminDashboardError && (
              <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {adminDashboardError}
              </p>
            )}
            {adminPanel === 'invalid-attendance' && invalidAttendanceError && (
              <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {invalidAttendanceError}
              </p>
            )}
            {adminPanel !== 'invalid-attendance' && isLoadingAdminDashboard && !adminDashboardSnapshot ? (
              <p className="mt-5 text-sm text-slate-500">Loading administrator dashboard details…</p>
            ) : adminPanel !== 'invalid-attendance' && adminDashboardError && !adminDashboardSnapshot ? null : (
              <div className="mt-5 overflow-x-auto">
                {adminPanel === 'no-login' || adminPanel === 'no-logout' ? (
                  (() => {
                    const records: AdminAttendanceException[] = adminPanel === 'no-login'
                      ? adminDashboardSnapshot?.no_login ?? []
                      : adminDashboardSnapshot?.no_logout ?? []
                    return records.length === 0 ? (
                      <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                        No matching attendance records.
                      </p>
                    ) : (
                      <table className="w-full min-w-[680px] text-left text-sm">
                        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                          <tr>
                            <th className="px-3 py-3">Employee</th>
                            <th className="px-3 py-3">Supervisor</th>
                            <th className="px-3 py-3">Date</th>
                            <th className="px-3 py-3">Time in</th>
                            <th className="px-3 py-3">Time out</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {records.map((record) => (
                            <tr key={`${record.employee_id}-${record.work_date}`}>
                              <td className="px-3 py-3">
                                <p className="font-semibold text-slate-900">{record.employee_name}</p>
                                <p className="text-xs text-slate-500">{record.employee_code}</p>
                              </td>
                              <td className="px-3 py-3">
                                <p className="font-semibold text-slate-900">{record.supervisor_name}</p>
                                <p className="text-xs text-slate-500">{record.supervisor_code}</p>
                              </td>
                              <td className="px-3 py-3 text-slate-600">
                                {new Date(`${record.work_date}T00:00:00+08:00`).toLocaleDateString('en-PH', { timeZone: 'Asia/Manila' })}
                              </td>
                              <td className="px-3 py-3 text-slate-600">
                                {record.time_in ? new Date(record.time_in).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' }) : '—'}
                              </td>
                              <td className="px-3 py-3 text-slate-600">
                                {record.time_out ? new Date(record.time_out).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' }) : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )
                  })()
                ) : adminPanel === 'invalid-attendance' ? (
                  isLoadingInvalidAttendance ? (
                    <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                      Loading invalid attendance…
                    </p>
                  ) : supervisorInvalidAttendance.length ? (
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                        <tr>
                          <th className="px-3 py-3">Employee</th>
                          <th className="px-3 py-3">Work date</th>
                          <th className="px-3 py-3">Clock in</th>
                          <th className="px-3 py-3">Clock out</th>
                          <th className="px-3 py-3 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {supervisorInvalidAttendance.map((record) => {
                          const isSaving = savingInvalidAttendanceId === record.id
                          return (
                            <tr key={record.id}>
                              <td className="px-3 py-3">
                                <p className="font-semibold text-slate-900">{record.employee_name}</p>
                                <p className="text-xs text-slate-500">{record.employee_code}</p>
                              </td>
                              <td className="px-3 py-3 text-slate-600">
                                {new Date(`${record.work_date}T00:00:00+08:00`).toLocaleDateString('en-PH', { timeZone: 'Asia/Manila' })}
                              </td>
                              <td className="px-3 py-3 text-slate-600">
                                {record.time_in ? new Date(record.time_in).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' }) : '—'}
                              </td>
                              <td className="px-3 py-3 text-slate-600">
                                {record.time_out ? new Date(record.time_out).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' }) : '—'}
                              </td>
                              <td className="px-3 py-3 text-right">
                                <button
                                  type="button"
                                  disabled={savingInvalidAttendanceId !== null}
                                  onClick={() => void approveInvalidAttendance(record.id)}
                                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {isSaving ? 'Approving…' : 'Approve'}
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  ) : (
                    <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                      There are no invalid attendance records awaiting review.
                    </p>
                  )
                ) : adminPanel === 'pending-leaves' ? (
                  adminDashboardSnapshot?.pending_leaves.length ? (
                    <table className="w-full min-w-[800px] text-left text-sm">
                      <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                        <tr>
                          <th className="px-3 py-3">Employee</th>
                          <th className="px-3 py-3">Application</th>
                          <th className="px-3 py-3">Leave</th>
                          <th className="px-3 py-3">Dates</th>
                          <th className="px-3 py-3">Requested</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {adminDashboardSnapshot.pending_leaves.map((leave) => (
                          <tr key={leave.id}>
                            <td className="px-3 py-3">
                              <p className="font-semibold text-slate-900">{leave.employee_name}</p>
                              <p className="text-xs text-slate-500">{leave.employee_code}</p>
                            </td>
                            <td className="px-3 py-3 text-slate-600">{leave.application_no}</td>
                            <td className="px-3 py-3 text-slate-600">{leave.leave_type}</td>
                            <td className="px-3 py-3 text-slate-600">
                              {new Date(leave.start_at).toLocaleDateString()} – {new Date(leave.end_at).toLocaleDateString()}
                            </td>
                            <td className="px-3 py-3 text-slate-600">{formatWeeklyHours(leave.requested_minutes / 60)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                      There are no pending leave requests.
                    </p>
                  )
                ) : adminDashboardSnapshot?.weekly_hours.length ? (
                  <table className="w-full min-w-[600px] text-left text-sm">
                    <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-3 py-3">Employee</th>
                        <th className="px-3 py-3">Hours this week</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {adminDashboardSnapshot.weekly_hours.map((employee) => (
                        <tr key={employee.employee_id}>
                          <td className="px-3 py-3">
                            <p className="font-semibold text-slate-900">{employee.employee_name}</p>
                            <p className="text-xs text-slate-500">{employee.employee_code}</p>
                          </td>
                          <td className="px-3 py-3 font-semibold text-slate-700">
                            {formatWeeklyHours(employee.minutes_worked / 60)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                    No completed attendance hours have been recorded this week.
                  </p>
                )}
              </div>
            )}
          </section>
        )}

        {role === 'supervisor' && isSupervisorLeavePanelOpen && (
          <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">Pending leave approvals</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Review leave applications from employees currently assigned to you.
                </p>
              </div>
              <span className="w-fit rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                {supervisorPendingLeaveCount} pending
              </span>
            </div>

            {supervisorLeavesError && (
              <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {supervisorLeavesError}
              </p>
            )}
            {isLoadingSupervisorLeaves ? (
              <p className="mt-5 text-sm text-slate-500">Loading pending leave applications…</p>
            ) : supervisorPendingLeaves.length === 0 ? (
              <p className="mt-5 rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                There are no pending leave applications assigned to you.
              </p>
            ) : (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[960px] text-left text-sm">
                  <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="px-3 py-3">Employee</th>
                      <th className="px-3 py-3">Leave</th>
                      <th className="px-3 py-3">Dates</th>
                      <th className="px-3 py-3">Reason</th>
                      <th className="px-3 py-3">Decision</th>
                      <th className="px-3 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {supervisorPendingLeaves.map((leave) => {
                      const decision = supervisorLeaveDecisions[leave.id] ?? ''
                      const isSaving = savingSupervisorLeaveId === leave.id
                      return (
                        <tr key={leave.id} className="align-top">
                          <td className="px-3 py-4">
                            <p className="font-semibold text-slate-900">{leave.employee_name}</p>
                            <p className="mt-1 text-xs text-slate-500">{leave.employee_no} · {leave.application_no}</p>
                          </td>
                          <td className="px-3 py-4">
                            <p className="font-semibold text-slate-800">{leave.leave_type_name}</p>
                            <p className="mt-1 text-xs text-slate-500">{formatLeaveBalance(leave.requested_minutes, leave.unit_type)}</p>
                          </td>
                          <td className="px-3 py-4 text-slate-600">
                            {new Date(leave.start_at).toLocaleString()} – {new Date(leave.end_at).toLocaleString()}
                          </td>
                          <td className="max-w-xs whitespace-normal px-3 py-4 text-slate-600">{leave.reason}</td>
                          <td className="px-3 py-4">
                            <label className="sr-only" htmlFor={`leave-decision-${leave.id}`}>Decision for {leave.employee_name}</label>
                            <select
                              id={`leave-decision-${leave.id}`}
                              value={decision}
                              disabled={isSaving}
                              onChange={(event) => setSupervisorLeaveDecisions((current) => ({
                                ...current,
                                [leave.id]: event.target.value as 'APPROVED' | 'REJECTED' | '',
                              }))}
                              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 disabled:opacity-50"
                            >
                              <option value="">Select decision</option>
                              <option value="APPROVED">Approve</option>
                              <option value="REJECTED">Reject</option>
                            </select>
                          </td>
                          <td className="px-3 py-4 text-right">
                            <button
                              type="button"
                              disabled={!decision || savingSupervisorLeaveId !== null}
                              onClick={() => void saveSupervisorLeaveDecision(leave.id)}
                              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {isSaving ? 'Saving…' : 'Save'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {role === 'supervisor' && isInvalidAttendancePanelOpen && (
          <section className="mt-6 rounded-2xl border border-amber-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">Invalid Attendance</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Review attendance recorded without an administrator-approved browser for employees assigned to you.
                </p>
              </div>
              <span className="w-fit rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                {supervisorInvalidAttendance.length} awaiting approval
              </span>
            </div>

            {invalidAttendanceError && (
              <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {invalidAttendanceError}
              </p>
            )}
            {isLoadingInvalidAttendance ? (
              <p className="mt-5 text-sm text-slate-500">Loading invalid attendance…</p>
            ) : supervisorInvalidAttendance.length === 0 ? (
              <p className="mt-5 rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                There are no invalid attendance records awaiting your approval.
              </p>
            ) : (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="px-3 py-3">Employee</th>
                      <th className="px-3 py-3">Work date</th>
                      <th className="px-3 py-3">Clock in</th>
                      <th className="px-3 py-3">Clock out</th>
                      <th className="px-3 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {supervisorInvalidAttendance.map((record) => {
                      const isSaving = savingInvalidAttendanceId === record.id
                      return (
                        <tr key={record.id}>
                          <td className="px-3 py-3">
                            <p className="font-semibold text-slate-900">{record.employee_name}</p>
                            <p className="text-xs text-slate-500">{record.employee_code}</p>
                          </td>
                          <td className="px-3 py-3 text-slate-600">
                            {new Date(`${record.work_date}T00:00:00+08:00`).toLocaleDateString('en-PH', { timeZone: 'Asia/Manila' })}
                          </td>
                          <td className="px-3 py-3 text-slate-600">
                            {record.time_in ? new Date(record.time_in).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' }) : '—'}
                          </td>
                          <td className="px-3 py-3 text-slate-600">
                            {record.time_out ? new Date(record.time_out).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' }) : '—'}
                          </td>
                          <td className="px-3 py-3 text-right">
                            <button
                              type="button"
                              disabled={savingInvalidAttendanceId !== null}
                              onClick={() => void approveInvalidAttendance(record.id)}
                              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {isSaving ? 'Approving…' : 'Approve'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {isAdmin && role !== 'employee' && isPendingListOpen && (
          <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">Pending device reviews</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Review the device and its associated employee, choose a decision, then save it.
                </p>
                {snapshotRefreshedAt && (
                  <p className="mt-1 text-xs text-slate-400">
                    Snapshot refreshed {new Date(snapshotRefreshedAt).toLocaleString()} · updates every 5 minutes
                  </p>
                )}
              </div>
              <span className="w-fit rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                {pendingDevices.length} pending
              </span>
            </div>

            {deviceError && (
              <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {deviceError}
              </p>
            )}

            {isLoadingDevices ? (
              <p className="mt-5 text-sm text-slate-500">Loading pending devices…</p>
            ) : deviceError && !hasLoadedDevices ? null : pendingDevices.length === 0 ? (
              <p className="mt-5 rounded-lg bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                There are no pending device registrations.
              </p>
            ) : (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <tr>
                      <th className="px-3 py-3">Employee</th>
                      <th className="px-3 py-3">Device</th>
                      <th className="px-3 py-3">Platform / details</th>
                      <th className="px-3 py-3">Submitted</th>
                      <th className="px-3 py-3">Decision</th>
                      <th className="px-3 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {pendingDevices.map((device) => {
                      const employeeName = device.employee_first_name && device.employee_last_name
                        ? `${device.employee_first_name} ${device.employee_last_name}`
                        : 'Employee record unavailable'
                      const draft = deviceReviewDrafts[device.id] ?? { status: '', reason: '' }
                      const isSaving = savingDeviceId === device.id
                      return (
                        <tr key={device.id} className="align-top">
                          <td className="px-3 py-4">
                            <p className="font-semibold text-slate-900">{employeeName}</p>
                            <p className="mt-1 text-xs text-slate-500">
                              {device.employee_no ?? device.employee_id ?? 'No employee linked'}
                            </p>
                          </td>
                          <td className="px-3 py-4">
                            <p className="font-semibold text-slate-900">{device.device_name || 'Unnamed device'}</p>
                            <p className="mt-1 break-all text-xs text-slate-500">{device.device_uuid}</p>
                            <p className="mt-1 text-xs text-slate-500">{device.registration_status}</p>
                          </td>
                          <td className="px-3 py-4 text-slate-600">
                            <p>{device.platform}</p>
                            <p className="mt-1 text-xs text-slate-500">
                              {[device.manufacturer, device.model, device.os_version, device.app_version]
                                .filter(Boolean)
                                .join(' · ') || 'No additional device details'}
                            </p>
                            <p className="mt-1 text-xs text-slate-500">
                              Enrollment IP: {device.enrollment_ip || 'Unavailable'}
                            </p>
                          </td>
                          <td className="px-3 py-4 text-slate-600">
                            {device.created_at ? new Date(device.created_at).toLocaleString() : '—'}
                          </td>
                          <td className="px-3 py-4">
                            <label className="sr-only" htmlFor={`device-decision-${device.id}`}>
                              Review decision for {employeeName}
                            </label>
                            <select
                              id={`device-decision-${device.id}`}
                              value={draft.status}
                              disabled={isSaving}
                              onChange={(event) => updateDeviceDraft(device.id, {
                                status: event.target.value as DeviceReviewStatus | '',
                              })}
                              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 disabled:opacity-50"
                            >
                              <option value="">Select decision</option>
                              <option value="APPROVED">Approve</option>
                              <option value="REJECTED">Reject</option>
                              <option value="REVOKED">Revoke</option>
                            </select>
                            {draft.status === 'REVOKED' && (
                              <div className="mt-2">
                                <label
                                  className="mb-1 block text-xs font-semibold text-slate-600"
                                  htmlFor={`device-revocation-reason-${device.id}`}
                                >
                                  Revocation reason (required)
                                </label>
                                <textarea
                                  id={`device-revocation-reason-${device.id}`}
                                  value={draft.reason}
                                  disabled={isSaving}
                                  maxLength={1000}
                                  rows={2}
                                  onChange={(event) => updateDeviceDraft(device.id, { reason: event.target.value })}
                                  className="w-56 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 disabled:opacity-50"
                                />
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-4 text-right">
                            <button
                              type="button"
                              disabled={
                                savingDeviceId !== null
                                || !draft.status
                                || (draft.status === 'REVOKED' && !draft.reason.trim())
                              }
                              onClick={() => void saveDeviceReview(device.id)}
                              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
                              aria-label={`Save review for ${employeeName}`}
                            >
                              {isSaving ? 'Saving…' : 'Save'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            {role === 'employee' ? (
              <>
                <LeaveBalanceGrid
                  balances={dashboardLeaveBalances}
                  isLoading={isLoadingLeaveDashboard}
                  error={leaveDashboardError}
                  refreshedAt={leaveDashboardRefreshedAt}
                />
                <WorkHoursCard
                  hours={data.workHours}
                  weeklyHoursWorked={weeklyHoursWorked}
                  isWeeklyHoursLoading={isLoadingRecentAttendance}
                />
                <RecentAttendanceTable
                  entries={recentAttendance}
                  isLoading={isLoadingRecentAttendance}
                  error={recentAttendanceError}
                  refreshedAt={attendanceSnapshotRefreshedAt}
                />
              </>
            ) : (
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-500">Role preview</h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  The production {role} dashboard can be connected to role-specific team and organization data
                  when those backend endpoints are available.
                </p>
              </div>
            )}
          </div>

          <div className="space-y-6">
            {role === 'employee' && (
              <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-500">My Overtime Applications</h2>
                <p className="mt-2 text-xs leading-5 text-slate-500">Apply using completed attendance and track your approval status.</p>
                <button type="button" onClick={() => onNavigate?.('overtime-application')} className="mt-4 w-full rounded-lg border border-indigo-200 px-4 py-2 text-sm font-semibold text-indigo-600 transition hover:bg-indigo-50">
                  Apply for Overtime
                </button>
              </section>
            )}
            {role === 'employee' && (
              <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-500">My Official Business</h2>
                <p className="mt-2 text-xs leading-5 text-slate-500">File client visits and field work outside your usual workplace, then track approval.</p>
                <button type="button" onClick={() => onNavigate?.('official-business')} className="mt-4 w-full rounded-lg border border-indigo-200 px-4 py-2 text-sm font-semibold text-indigo-600 transition hover:bg-indigo-50">
                  File Official Business
                </button>
              </section>
            )}
            {role === 'supervisor' ? (
              <SupervisorPendingLeavesCard
                applications={supervisorPendingLeaves}
                isLoading={isLoadingSupervisorLeaves}
                error={supervisorLeavesError}
              />
            ) : role !== 'administrator' ? (
              <LeaveRequestsCard
                requests={dashboardLeaveRequests}
                onApply={role === 'employee' ? () => onNavigate?.('leave-application') : undefined}
              />
            ) : null}
            <HolidaysCard holidays={data.upcomingHolidays} />
            <AnnouncementsCard announcements={data.announcements} />
          </div>
        </div>
      </main>
    </div>
  )
}
