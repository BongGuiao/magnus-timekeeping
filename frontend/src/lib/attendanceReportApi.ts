import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface AttendanceReportOvertime {
  application_no: string
  overtime_type: string
  requested_minutes: number
  approved_minutes: number | null
  payable_minutes: number | null
  status: string
}

export interface AttendanceReportLeave {
  application_no: string
  leave_type: string
  requested_minutes: number
  paid_minutes: number
  unpaid_minutes: number
  status: string
}

export interface AttendanceReportOfficialBusiness {
  request_no: string
  requested_minutes: number
  approved_minutes: number | null
  credited_minutes: number
  status: string
  start_at: string
  end_at: string
}

export interface AttendanceDetailReportRecord {
  attendance_id: string | null
  employee_no: string
  employee_name: string
  work_date: string
  schedule_code: string | null
  expected_clock_in_at: string | null
  expected_clock_out_at: string | null
  clock_in_at: string | null
  clock_out_at: string | null
  record_status: string
  attendance_mode: 'PUNCH_REQUIRED' | 'SCHEDULE_CREDITED'
  is_absent: boolean
  work_type: string
  day_type: string
  late_minutes: number
  undertime_minutes: number
  worked_minutes: number | null
  regular_overtime_minutes: number
  night_differential_minutes: number
  night_differential_overtime_minutes: number
  overtime_applications: AttendanceReportOvertime[]
  leave_applications: AttendanceReportLeave[]
  official_business_requests: AttendanceReportOfficialBusiness[]
}

export interface AttendanceDetailReportFilters {
  from_date: string
  to_date: string
  scope: 'own' | 'team' | 'organization'
  employee_no?: string
  cutoff_id?: string
}

export interface AttendanceFinalizationCutoff {
  cutoff_id: string
  cutoff_code: string
  payroll_group_name: string
  period_start: string
  period_end: string
  attendance_deadline: string | null
  attendance_finalized_at: string | null
  attendance_finalized_by: string | null
  attendance_result_count: number
}

export interface AttendanceFinalizationResult {
  cutoff_id: string
  finalized_at: string
  finalized_by: string
  attendance_result_count: number
}

export interface OrgUnitAttendanceSummary {
  org_unit_id: string | null
  org_unit_code: string
  org_unit_name: string
  employee_count: number
  total_attendance: number
  approved_leave_days: number
  approved_leave_minutes: number
  approved_overtime_count: number
  approved_overtime_minutes: number
  approved_ob_count: number
  approved_ob_minutes: number
  regular_overtime_minutes: number
  night_differential_minutes: number
  night_differential_overtime_minutes: number
  late_minutes: number
  undertime_minutes: number
}

export async function fetchOrgUnitAttendanceSummary(
  fromDate: string,
  toDate: string,
): Promise<OrgUnitAttendanceSummary[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OrgUnitAttendanceSummary[]>>(
      '/attendance/reports/attendance-summary-by-org-unit',
      { params: { from_date: fromDate, to_date: toDate } },
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load the Org Unit attendance summary.'))
  }
}

export async function fetchAttendanceDetailReport(
  filters: AttendanceDetailReportFilters,
): Promise<AttendanceDetailReportRecord[]> {
  const { employee_no, cutoff_id, ...requiredFilters } = filters
  const params = {
    ...requiredFilters,
    ...(employee_no?.trim() ? { employee_no: employee_no.trim() } : {}),
    ...(cutoff_id ? { cutoff_id } : {}),
  }
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceDetailReportRecord[]>>(
      '/attendance/reports/attendance-detail',
      { params },
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load attendance detail report.'))
  }
}

export async function fetchAttendanceFinalizationCutoffs(): Promise<AttendanceFinalizationCutoff[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceFinalizationCutoff[]>>(
      '/attendance/reports/attendance-cutoffs',
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load attendance cutoff status.'))
  }
}

export async function finalizeAttendanceCutoff(
  cutoffId: string,
): Promise<AttendanceFinalizationResult> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<AttendanceFinalizationResult>>(
      `/attendance/reports/attendance-cutoffs/${encodeURIComponent(cutoffId)}/finalize`,
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not finalize attendance for this cutoff.'))
  }
}
