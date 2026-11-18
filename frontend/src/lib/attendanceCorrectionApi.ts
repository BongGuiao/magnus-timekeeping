import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface AttendanceCorrection {
  id: string
  employee_id: string
  employee_code: string
  employee_name: string
  work_date: string
  original_clock_in_at: string | null
  original_clock_out_at: string | null
  requested_clock_in_at: string
  requested_clock_out_at: string
  reason: string
  supporting_reference: string | null
  status: string
  created_at: string
  reviewed_at: string | null
  review_notes: string | null
  row_version: number
}

export interface CorrectionDay {
  work_date: string
  clock_in_at: string | null
  clock_out_at: string | null
  expected_clock_in_at: string
  expected_clock_out_at: string
}

const path = '/attendance/corrections'
const hrExceptionsPath = `${path}/hr-exceptions`

export interface AttendanceExceptionSchedule {
  schedule_code: string
  expected_clock_in_at: string
  expected_clock_out_at: string
  schedule_fingerprint: string
  schedule_context: {
    grace_minutes: number
    ot_eligible: boolean
    minimum_ot_minutes: number
    pre_shift_ot_allowed: boolean
    break_rules: Array<{ segment_id: string; break_slot: string; break_minutes: number; auto_deduct: boolean }>
  }
}

export async function fetchAttendanceExceptions(): Promise<AttendanceCorrection[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceCorrection[]>>(hrExceptionsPath)
    if (!Array.isArray(response.data.data)) throw new Error('Invalid attendance exceptions response.')
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load attendance exceptions.'))
  }
}

export async function fetchAttendanceExceptionSchedule(id: string): Promise<AttendanceExceptionSchedule> {
  try {
    return (await apiClient.get<ApiSuccessEnvelope<AttendanceExceptionSchedule>>(`${hrExceptionsPath}/${id}/schedule`)).data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not verify the schedule.'))
  }
}

export async function resolveAttendanceException(
  request: AttendanceCorrection, schedule: AttendanceExceptionSchedule, notes: string,
): Promise<void> {
  try {
    await apiClient.post(`${hrExceptionsPath}/${request.id}/resolve`, {
      row_version: request.row_version,
      schedule_fingerprint: schedule.schedule_fingerprint,
      review_notes: notes.trim(),
    })
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not resolve the attendance exception.'))
  }
}

export async function fetchCorrectionDay(workDate: string): Promise<CorrectionDay> {
  try {
    return (await apiClient.get<ApiSuccessEnvelope<CorrectionDay>>(`${path}/day`, { params: { work_date: workDate } })).data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load attendance for correction.'))
  }
}

export async function fetchAttendanceCorrections(scope: 'own' | 'team'): Promise<AttendanceCorrection[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<AttendanceCorrection[]>>(scope === 'team' ? `${path}/pending` : path)
    if (!Array.isArray(response.data.data)) throw new Error('Invalid attendance corrections response.')
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load attendance correction requests.'))
  }
}

export async function submitAttendanceCorrection(payload: {
  work_date: string
  requested_clock_in_at: string
  requested_clock_out_at: string
  reason: string
  supporting_reference: string | null
}): Promise<AttendanceCorrection> {
  try {
    return (await apiClient.post<ApiSuccessEnvelope<AttendanceCorrection>>(path, payload)).data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not submit the attendance correction.'))
  }
}

export async function decideAttendanceCorrection(request: AttendanceCorrection, decision: 'APPROVED' | 'REJECTED', notes: string): Promise<AttendanceCorrection> {
  try {
    return (await apiClient.post<ApiSuccessEnvelope<AttendanceCorrection>>(`${path}/${request.id}/decision`, {
      decision, row_version: request.row_version, review_notes: notes.trim(),
    })).data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not save the correction decision.'))
  }
}
