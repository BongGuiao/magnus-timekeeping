export interface LeaveBalance {
  type: string
  label: string
  allotted: number
  used: number
  available?: number
  unitType?: 'MINUTES' | 'HOURS' | 'DAYS'
}

export interface AttendanceExceptions {
  noLogin: number
  noLogout: number
  periodLabel: string
}

export interface TodayStatus {
  clockInAt: string | null
  clockOutAt: string | null
  isOnBreak: boolean
}

export interface WorkHoursSummary {
  weeklyHours: number
  weeklyTarget: number
  monthlyHours: number
  monthlyTarget: number
}

export interface AttendanceLogEntry {
  date: string
  attendanceId?: string
  overtimeApplications?: OvertimeApplicationEntry[]
  expectedTimeIn?: string | null
  expectedTimeOut?: string | null
  timeIn: string | null
  timeOut: string | null
  minutesWorked?: number | null
  lateMinutes?: number
  undertimeMinutes?: number
  calculatedOtMinutes?: number
  overtimeHours?: number
  regularOvertimeMinutes?: number
  regularOvertimeHours?: number
  nightDifferentialOvertimeMinutes?: number
  nightDifferentialOvertimeHours?: number
  nightDifferentialMinutes?: number
  nightDifferentialHours?: number
  overtimeRequestStatus?: 'PENDING' | 'APPROVED' | 'REJECTED' | null
  requestedRegularOvertimeMinutes?: number
  requestedNightDifferentialOvertimeMinutes?: number
  requestedNightDifferentialMinutes?: number
  approvedRegularOvertimeMinutes?: number
  approvedNightDifferentialOvertimeMinutes?: number
  approvedNightDifferentialMinutes?: number
  isLate?: boolean
  isUndertime?: boolean
  status: 'present' | 'late' | 'no-login' | 'no-logout' | 'on-leave'
}

export type OvertimeApplicationType =
  | 'REGULAR_OVERTIME'
  | 'NIGHT_DIFFERENTIAL_OVERTIME'
  | 'NIGHT_DIFFERENTIAL'

export interface OvertimeApplicationEntry {
  id: string
  applicationNo: string
  overtimeType: OvertimeApplicationType
  requestedMinutes: number
  supervisorApprovedMinutes: number | null
  finalPayableMinutes: number | null
  status: string
}

export interface LeaveRequest {
  id: string
  type: string
  startDate: string
  endDate: string
  status: string
}

export interface Holiday {
  date: string
  name: string
}

export interface Announcement {
  id: string
  title: string
  postedAt: string
}

export interface EmployeeDashboardData {
  employeeName: string
  employeeCode: string
  today: TodayStatus
  workHours: WorkHoursSummary
  leaveBalances: LeaveBalance[]
  attendanceExceptions: AttendanceExceptions
  recentAttendance: AttendanceLogEntry[]
  leaveRequests: LeaveRequest[]
  upcomingHolidays: Holiday[]
  announcements: Announcement[]
}
