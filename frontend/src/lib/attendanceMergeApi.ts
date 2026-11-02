import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface AttendanceMergeScheduleTemplate {
  id: string
  schedule_code: string
  schedule_name: string
}

export interface AttendanceMergeSourceAudit {
  source_attendance_id: string
  source_snapshot: Record<string, string | boolean | null>
}

export interface AttendanceMergeAudit {
  merge_id: string
  canonical_attendance_id: string
  employee_id: string
  work_date: string
  schedule_template_id: string
  schedule_code: string
  merged_by: string | null
  merged_at: string
  reason: string
  canonical_clock_in_at: string
  canonical_clock_out_at: string
  calculation_snapshot: Record<string, string | number>
  sources: AttendanceMergeSourceAudit[]
}

export interface CreateAttendanceMergeResult {
  merge_id: string
  canonical_attendance_id: string
  employee_id: string
  work_date: string
  clock_in_at: string
  clock_out_at: string
  schedule_code: string
}

export async function fetchMergeScheduleTemplates(
  attendanceId: string,
): Promise<AttendanceMergeScheduleTemplate[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceMergeScheduleTemplate[]>>(
      '/attendance/attendance-merges/schedule-templates',
      { params: { attendance_id: attendanceId } },
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load schedules for this attendance date.'))
  }
}

export async function createAttendanceMerge(payload: {
  source_attendance_ids: string[]
  schedule_template_id: string
  reason: string
  verified_clock_out_at?: string | null
}): Promise<CreateAttendanceMergeResult> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<CreateAttendanceMergeResult>>(
      '/attendance/attendance-merges',
      payload,
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not merge the attendance records.'))
  }
}

export async function fetchAttendanceMergeAudit(
  canonicalAttendanceId: string,
): Promise<AttendanceMergeAudit> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceMergeAudit>>(
      `/attendance/attendance-merges/${encodeURIComponent(canonicalAttendanceId)}/audit`,
    )
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load the attendance merge audit.'))
  }
}
