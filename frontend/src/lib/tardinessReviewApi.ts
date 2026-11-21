import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface TardinessAttendanceRecord {
  attendance_id: string
  work_date: string
  expected_clock_in_at: string | null
  clock_in_at: string | null
  late_minutes: number
  attendance_mode: 'PUNCH_REQUIRED' | 'SCHEDULE_CREDITED'
}

export interface TardinessReviewCandidate {
  employee_id: string
  employee_no: string
  employee_name: string
  late_dates: string[]
  duplicate_dates: string[]
  pending_correction_dates: string[]
  records: TardinessAttendanceRecord[]
}

export interface TardinessReview {
  period_start: string
  period_end: string
  candidates: TardinessReviewCandidate[]
}

export async function fetchTardinessReview(): Promise<TardinessReview> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<TardinessReview>>('/attendance/tardiness-review')
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load the tardiness review.'))
  }
}
