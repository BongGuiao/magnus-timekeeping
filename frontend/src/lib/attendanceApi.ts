import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import {
  checkAttendanceBrowserRegistration,
  createAttendanceDeviceProof,
  registerAttendanceBrowser,
} from './attendanceDevice'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { BreakResult, ClockResult, LastAttendance } from '../types/attendance'
import type {
  AttendanceLogEntry,
  OvertimeApplicationEntry,
  OvertimeApplicationType,
} from '../types/dashboard'

export interface AttendanceLocation {
  latitude: number
  longitude: number
  accuracyMeters: number
}

export { checkAttendanceBrowserRegistration, registerAttendanceBrowser }

// Relative path: nginx proxies /attendance/* to the FastAPI backend (see nginx/default.conf).
// user_id narrows the face match to a single enrollment row instead of scanning every employee.
export function getAttendanceErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) {
    return error instanceof Error ? error.message : fallback
  }

  const body = error.response?.data as ApiErrorEnvelope | undefined
  const detail: unknown = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item: unknown) => {
      if (typeof item !== 'object' || item === null || !('msg' in item)) return []
      const message = item.msg
      if (typeof message !== 'string') return []
      const location = 'loc' in item && Array.isArray(item.loc)
        ? item.loc.filter((part): part is string | number => typeof part === 'string' || typeof part === 'number')
        : []
      return [`${location.length ? `${location.join(' → ')}: ` : ''}${message}`]
    })
    if (messages.length) return messages.join('; ')
  }

  return fallback
}

export async function clockAttendance(
  file: File,
  userId: string,
  clockOutConfirmed = false,
  location?: AttendanceLocation,
  browserApproved = true,
): Promise<ClockResult> {
  try {
    const formData = new FormData()
    formData.append('file', file, file.name)
    formData.append('user_id', String(userId))
    formData.append('clock_out_confirmed', String(clockOutConfirmed))
    if (browserApproved) {
      const proof = await createAttendanceDeviceProof(userId, 'CLOCK')
      formData.append('device_challenge_id', proof.challengeId)
      formData.append('device_signature', proof.signature)
    }
    if (location) {
      formData.append('latitude', String(location.latitude))
      formData.append('longitude', String(location.longitude))
      formData.append('gps_accuracy_meters', String(location.accuracyMeters))
    }

    const response = await apiClient.post<ApiSuccessEnvelope<ClockResult>>('/attendance/clock', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not record attendance. Please try again.'))
  }
}

export async function clockBreak(file: File, breakType: string, userId: string, location?: AttendanceLocation): Promise<BreakResult> {
  try {
    const proof = await createAttendanceDeviceProof(userId, 'BREAK')
    const formData = new FormData()
    formData.append('file', file, file.name)
    formData.append('break_type', breakType)
    formData.append('user_id', String(userId))
    formData.append('device_challenge_id', proof.challengeId)
    formData.append('device_signature', proof.signature)
    if (location) {
      formData.append('latitude', String(location.latitude))
      formData.append('longitude', String(location.longitude))
      formData.append('gps_accuracy_meters', String(location.accuracyMeters))
    }

    const response = await apiClient.post<ApiSuccessEnvelope<BreakResult>>('/attendance/clock-break', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not record break. Please try again.'))
  }
}

export interface AttendanceClockPolicy {
  channel: 'kiosk' | 'mobile' | 'desktop'
  geofence_required: boolean
  client_ip: string | null
}

export async function fetchClockPolicy(): Promise<AttendanceClockPolicy> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceClockPolicy>>('/attendance/clock-policy')
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load the attendance clock policy.'))
  }
}

export async function fetchLastAttendance(userId: string): Promise<LastAttendance | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<LastAttendance | null>>('/attendance/last', {
      params: { user_id: userId },
    })
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load the last attendance record.'))
  }
}

interface RecentAttendanceSnapshot {
  records: {
    attendance_id: string
    overtime_applications?: {
      id: string
      application_no: string
      overtime_type: OvertimeApplicationType
      requested_minutes: number
      supervisor_approved_minutes: number | null
      final_payable_minutes: number | null
      status: string
    }[]
    date: string
    expected_time_in?: string | null
    expected_time_out?: string | null
    time_in: string | null
    time_out: string | null
    minutes_worked: number | null
    late_minutes?: number
    undertime_minutes?: number
    calculated_ot_minutes?: number
    overtime_hours?: number
    regular_overtime_minutes?: number
    regular_overtime_hours?: number
    night_differential_overtime_minutes?: number
    night_differential_overtime_hours?: number
    night_differential_minutes?: number
    night_differential_hours?: number
    overtime_request_status?: 'PENDING' | 'APPROVED' | 'REJECTED' | null
    requested_regular_overtime_minutes?: number
    requested_night_differential_overtime_minutes?: number
    requested_night_differential_minutes?: number
    approved_regular_overtime_minutes?: number
    approved_night_differential_overtime_minutes?: number
    approved_night_differential_minutes?: number
    is_late?: boolean
    is_undertime?: boolean
    status: AttendanceLogEntry['status']
  }[]
  weekly_hours_worked: number
  weekly_minutes_worked: number
  missed_clock_ins_this_month: number
  refreshed_at: string
}

export interface AdminAttendanceException {
  employee_id: string
  employee_code: string
  employee_name: string
  supervisor_code: string
  supervisor_name: string
  work_date: string
  time_in: string | null
  time_out: string | null
}

export interface AdminPendingLeave {
  id: string
  application_no: string
  employee_id: string
  employee_code: string
  employee_name: string
  leave_type: string
  start_at: string
  end_at: string
  requested_minutes: number
  status: string
}

export interface AdminWeeklyHours {
  employee_id: string
  employee_code: string
  employee_name: string
  hours_worked: number
  minutes_worked: number
}

export interface AdminDashboardSnapshot {
  no_login: AdminAttendanceException[]
  no_logout: AdminAttendanceException[]
  pending_leaves: AdminPendingLeave[]
  weekly_hours: AdminWeeklyHours[]
  refreshed_at: string
}

export interface SupervisorInvalidAttendance {
  id: string
  employee_id: string
  employee_code: string
  employee_name: string
  work_date: string
  time_in: string | null
  time_out: string | null
}

export interface OvertimeRequest {
  attendance_id: string
  employee_id: string
  employee_code: string
  employee_name: string
  work_date: string
  calculated_regular_overtime_minutes: number
  calculated_night_differential_overtime_minutes: number
  calculated_night_differential_minutes: number
  requested_regular_overtime_minutes: number
  requested_night_differential_overtime_minutes: number
  requested_night_differential_minutes: number
  overtime_request_status: 'PENDING' | 'APPROVED' | 'REJECTED' | null
  approved_regular_overtime_minutes: number
  approved_night_differential_overtime_minutes: number
  approved_night_differential_minutes: number
}

export interface OvertimeRequestAmounts {
  regular_overtime_minutes: number
  night_differential_overtime_minutes: number
  night_differential_minutes: number
}

export interface OvertimeApplicationInput {
  overtime_type: OvertimeApplicationType
  requested_start_at?: string
  requested_end_at?: string
  requested_minutes: number
  reason: string
  work_accomplished?: string | null
}

export interface OvertimePayrollCutoff {
  cutoff_code: string
  period_start: string
  period_end: string
}

export async function fetchOvertimeAttendanceOptions(): Promise<{
  cutoff: OvertimePayrollCutoff
  entries: AttendanceLogEntry[]
}> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<{
      cutoff: OvertimePayrollCutoff
      records: RecentAttendanceSnapshot['records']
    }>>('/attendance/overtime-attendance-options')
    return {
      cutoff: response.data.data.cutoff,
      entries: response.data.data.records.map((record) => ({
        attendanceId: record.attendance_id,
        date: record.date,
        expectedTimeIn: record.expected_time_in,
        expectedTimeOut: record.expected_time_out,
        timeIn: record.time_in,
        timeOut: record.time_out,
        regularOvertimeMinutes: record.regular_overtime_minutes,
        nightDifferentialOvertimeMinutes: record.night_differential_overtime_minutes,
        nightDifferentialMinutes: record.night_differential_minutes,
        status: record.status,
      })),
    }
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load completed attendance for the current payroll cutoff.'))
  }
}

export interface OvertimeApplication {
  id: string
  application_no: string
  attendance_record_id: string
  employee_id: string
  employee_code: string
  employee_name: string
  attendance_date: string
  requested_start_at: string
  requested_end_at: string
  potential_ot_minutes: number
  requested_minutes: number
  system_validated_minutes: number | null
  supervisor_approved_minutes: number | null
  final_payable_minutes: number | null
  overtime_type: OvertimeApplicationType
  reason: string
  work_accomplished: string | null
  validation_status: string | null
  status: string
  payroll_posted: boolean
}

export async function submitOvertimeApplication(
  attendanceId: string,
  payload: OvertimeApplicationInput,
): Promise<OvertimeApplication> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OvertimeApplication>>(
      `/attendance/overtime-applications/${encodeURIComponent(attendanceId)}`,
      payload,
    )
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not submit the overtime application.'))
  }
}

export async function fetchPendingOvertimeApplications(): Promise<OvertimeApplication[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OvertimeApplication[]>>(
      '/attendance/overtime-applications/pending',
    )
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load pending overtime applications.'))
  }
}

export async function fetchMyOvertimeApplications(): Promise<OvertimeApplication[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OvertimeApplication[]>>('/attendance/overtime-applications')
    if (!Array.isArray(response.data.data)) throw new Error('The overtime applications response was not a list.')
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load your overtime applications.'))
  }
}

export async function decideOvertimeApplication(
  applicationId: string,
  decision: 'APPROVED' | 'REJECTED',
  supervisorApprovedMinutes: number,
): Promise<OvertimeApplication> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OvertimeApplication>>(
      `/attendance/overtime-applications/${encodeURIComponent(applicationId)}/decision`,
      { decision, supervisor_approved_minutes: supervisorApprovedMinutes },
    )
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not save the overtime application decision.'))
  }
}

export async function submitOvertimeRequest(
  attendanceId: string,
  amounts: OvertimeRequestAmounts,
): Promise<OvertimeRequest> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OvertimeRequest>>(
      `/attendance/overtime/${encodeURIComponent(attendanceId)}/request`,
      amounts,
    )
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not submit the overtime request.'))
  }
}

export async function fetchPendingOvertimeRequests(): Promise<OvertimeRequest[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OvertimeRequest[]>>('/attendance/overtime/pending')
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load pending overtime requests.'))
  }
}

export async function decideOvertimeRequest(
  attendanceId: string,
  decision: 'APPROVED' | 'REJECTED',
  amounts: OvertimeRequestAmounts,
): Promise<OvertimeRequest> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OvertimeRequest>>(
      `/attendance/overtime/${encodeURIComponent(attendanceId)}/decision`,
      { decision, ...amounts },
    )
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not save the overtime approval.'))
  }
}

export async function fetchSupervisorInvalidAttendance(): Promise<SupervisorInvalidAttendance[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<SupervisorInvalidAttendance[]>>(
      '/attendance/supervisor/invalid-attendance',
    )
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load invalid attendance for your team.'))
  }
}

export async function approveSupervisorInvalidAttendance(attendanceId: string): Promise<void> {
  try {
    await apiClient.post<ApiSuccessEnvelope<SupervisorInvalidAttendance>>(
      `/attendance/supervisor/invalid-attendance/${encodeURIComponent(attendanceId)}/approve`,
    )
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not approve this attendance record.'))
  }
}

export async function fetchAdminDashboardSnapshot(): Promise<AdminDashboardSnapshot> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AdminDashboardSnapshot>>('/attendance/admin-dashboard')
    return response.data.data
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load administrator dashboard details.'))
  }
}

export async function fetchRecentAttendanceSnapshot(): Promise<{
  entries: AttendanceLogEntry[]
  weeklyHoursWorked: number
  missedClockInsThisMonth: number
  refreshedAt: string
}> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<RecentAttendanceSnapshot>>('/attendance/recent', {
      params: { force_refresh: true },
    })
    return {
      entries: response.data.data.records.map((record) => ({
        date: record.date,
        attendanceId: record.attendance_id,
        overtimeApplications: (record.overtime_applications ?? []).map((application): OvertimeApplicationEntry => ({
          id: application.id,
          applicationNo: application.application_no,
          overtimeType: application.overtime_type,
          requestedMinutes: application.requested_minutes,
          supervisorApprovedMinutes: application.supervisor_approved_minutes,
          finalPayableMinutes: application.final_payable_minutes,
          status: application.status,
        })),
        expectedTimeIn: record.expected_time_in,
        expectedTimeOut: record.expected_time_out,
        timeIn: record.time_in,
        timeOut: record.time_out,
        minutesWorked: record.minutes_worked,
        lateMinutes: record.late_minutes ?? 0,
        undertimeMinutes: record.undertime_minutes ?? 0,
        calculatedOtMinutes: record.calculated_ot_minutes ?? 0,
        overtimeHours: record.overtime_hours ?? 0,
        regularOvertimeMinutes: record.regular_overtime_minutes ?? 0,
        regularOvertimeHours: record.regular_overtime_hours ?? 0,
        nightDifferentialOvertimeMinutes: record.night_differential_overtime_minutes ?? 0,
        nightDifferentialOvertimeHours: record.night_differential_overtime_hours ?? 0,
        nightDifferentialMinutes: record.night_differential_minutes ?? 0,
        nightDifferentialHours: record.night_differential_hours ?? 0,
        overtimeRequestStatus: record.overtime_request_status,
        requestedRegularOvertimeMinutes: record.requested_regular_overtime_minutes ?? 0,
        requestedNightDifferentialOvertimeMinutes: record.requested_night_differential_overtime_minutes ?? 0,
        requestedNightDifferentialMinutes: record.requested_night_differential_minutes ?? 0,
        approvedRegularOvertimeMinutes: record.approved_regular_overtime_minutes ?? 0,
        approvedNightDifferentialOvertimeMinutes: record.approved_night_differential_overtime_minutes ?? 0,
        approvedNightDifferentialMinutes: record.approved_night_differential_minutes ?? 0,
        isLate: record.is_late ?? record.status === 'late',
        isUndertime: record.is_undertime ?? false,
        status: record.status,
      })),
      weeklyHoursWorked: response.data.data.weekly_minutes_worked / 60,
      missedClockInsThisMonth: response.data.data.missed_clock_ins_this_month,
      refreshedAt: response.data.data.refreshed_at,
    }
  } catch (err) {
    throw new Error(getAttendanceErrorMessage(err, 'Could not load recent attendance.'))
  }
}
