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
}

export async function fetchAttendanceDetailReport(
  filters: AttendanceDetailReportFilters,
): Promise<AttendanceDetailReportRecord[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceDetailReportRecord[]>>(
      '/attendance/reports/attendance-detail',
      { params: filters },
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load attendance detail report.'))
  }
}
