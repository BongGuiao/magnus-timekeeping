import { apiClient } from './apiClient'
import { getAttendanceErrorMessage } from './attendanceApi'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface RegularizationCandidate {
  assignment_id: string
  employee_id: string
  employee_no: string
  employee_name: string
  company_name: string
  org_unit_name: string | null
  employment_type: string
  hire_date: string
  six_month_date: string
  days_remaining: number
}

export interface RegularizationReview {
  as_of: string
  candidates: RegularizationCandidate[]
  notification_pending: boolean
}

export async function fetchRegularizationReview(): Promise<RegularizationReview> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<RegularizationReview>>('/employees/regularization-review')
    return response.data.data
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not load regularization candidates.'))
  }
}

export async function dismissRegularizationNotification(date: string): Promise<void> {
  try {
    await apiClient.post('/employees/regularization-review/dismiss', { notification_date: date })
  } catch (error) {
    throw new Error(getAttendanceErrorMessage(error, 'Could not dismiss the regularization notification.'))
  }
}
