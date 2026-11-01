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
