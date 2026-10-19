import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export type EmergencyScheduleRequestStatus = 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED'
export type EmergencyScheduleDecision = 'APPROVED' | 'REJECTED'

export interface EmergencyScheduleTemplateOption {
  id: string
  schedule_code: string
  schedule_name: string
  schedule_type: string
}

export interface EmergencyScheduleRequest {
  id: string
  employee_code: string
  employee_name: string
  schedule_code: string
  schedule_name: string
  work_date: string
  reason: string
  status: EmergencyScheduleRequestStatus
  requested_at: string
  reviewed_at: string | null
  review_remarks: string | null
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(typeof body?.detail === 'string' ? body.detail : fallback)
  }
  throw error
}

export async function fetchEmergencyScheduleTemplates(
  workDate: string,
): Promise<EmergencyScheduleTemplateOption[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmergencyScheduleTemplateOption[]>>(
      '/emergency-schedule-requests/templates',
      { params: { work_date: workDate } },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load schedule templates for this date.')
  }
}

export async function fetchMyEmergencyScheduleRequests(): Promise<EmergencyScheduleRequest[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmergencyScheduleRequest[]>>(
      '/emergency-schedule-requests',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your emergency schedule requests.')
  }
}

export async function submitEmergencyScheduleRequest(input: {
  schedule_template_id: string
  work_date: string
  reason: string
}): Promise<EmergencyScheduleRequest> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmergencyScheduleRequest>>(
      '/emergency-schedule-requests',
      input,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not submit the emergency schedule request.')
  }
}

export async function fetchPendingEmergencyScheduleRequests(): Promise<EmergencyScheduleRequest[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmergencyScheduleRequest[]>>(
      '/emergency-schedule-requests/pending',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load emergency schedule requests for review.')
  }
}

export async function reviewEmergencyScheduleRequest(
  requestId: string,
  decision: EmergencyScheduleDecision,
  remarks: string,
): Promise<EmergencyScheduleRequest> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmergencyScheduleRequest>>(
      `/emergency-schedule-requests/${requestId}/review`,
      { decision, remarks: remarks.trim() || null },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not review the emergency schedule request.')
  }
}
