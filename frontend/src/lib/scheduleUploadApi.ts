import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export type ScheduleUploadBatchStatus = 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'CANCELLED'

export interface ScheduleUploadRowResult {
  row_no: number
  employee_code: string
  employee_name: string | null
  schedule_code: string
  schedule_name: string | null
  assignment_type: string
  effective_from: string | null
  effective_to: string | null
  rest_day_pattern_code: string | null
  reason: string | null
  is_valid: boolean
  errors: string[]
  effects: string[]
  supervisor_employee_code?: string | null
}

export interface ScheduleUploadPreview {
  is_valid: boolean
  error_count: number
  file_errors: string[]
  rows: ScheduleUploadRowResult[]
}

export interface ScheduleUploadBatchSummary {
  id: string
  batch_no: string
  supervisor_employee_id: string
  supervisor_name: string
  uploaded_by: string
  file_name: string
  row_count: number
  status: ScheduleUploadBatchStatus
  submitted_at: string
  reviewed_by: string | null
  reviewed_at: string | null
  review_remarks: string | null
}

export interface ScheduleUploadBatchRow {
  row_no: number
  employee_id: string
  employee_code: string
  employee_name: string
  schedule_code: string
  assignment_type: string
  effective_from: string
  effective_to: string | null
  rest_day_pattern_code: string | null
  reason: string | null
  assignment_id: string | null
}

export interface ScheduleUploadBatch extends ScheduleUploadBatchSummary {
  rows: ScheduleUploadBatchRow[]
}

export interface ScheduleWorkSegment {
  start_time: string
  end_time: string
  end_day_offset: number
}

export interface MyScheduleAssignment {
  assignment_id: string
  schedule_code: string
  schedule_name: string
  schedule_type: string
  assignment_type: string
  effective_from: string
  effective_to: string | null
  rest_day_pattern_code: string | null
  rest_day_pattern_name: string | null
  approved_at: string | null
  work_segments: ScheduleWorkSegment[]
}

export const SCHEDULE_UPLOAD_STATUS_LABELS: Record<ScheduleUploadBatchStatus, string> = {
  PENDING_APPROVAL: 'Pending approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  CANCELLED: 'Cancelled',
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(typeof body?.detail === 'string' ? body.detail : fallback)
  }
  throw error
}

function fileForm(file: File): FormData {
  const form = new FormData()
  form.append('file', file)
  return form
}

// The client defaults to JSON, which would make axios serialize FormData as JSON.
const multipart = { headers: { 'Content-Type': 'multipart/form-data' } }

const hrModeParams = { dashboard_role_code: 'HR_ADMIN' }

export function isHrScheduleUploadMode(roleCodes: string[], selectedRoleCode: string): boolean {
  return selectedRoleCode === 'HR_ADMIN' && roleCodes.includes('HR_ADMIN')
}

export async function downloadScheduleUploadTemplate(hrAdmin = false): Promise<Blob> {
  try {
    const response = await apiClient.get<Blob>(
      hrAdmin ? '/schedule-uploads/hr-admin/template' : '/schedule-uploads/template',
      { responseType: 'blob', ...(hrAdmin ? { params: hrModeParams } : {}) },
    )
    return response.data
  } catch (error) {
    return rethrowApiError(error, 'Could not download the schedule upload template.')
  }
}

export async function previewScheduleUpload(file: File, hrAdmin = false): Promise<ScheduleUploadPreview> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleUploadPreview>>(
      hrAdmin ? '/schedule-uploads/hr-admin/preview' : '/schedule-uploads/preview',
      fileForm(file),
      { ...multipart, ...(hrAdmin ? { params: hrModeParams } : {}) },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not check the schedule file.')
  }
}

export async function submitScheduleUpload(file: File): Promise<ScheduleUploadBatch> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleUploadBatch>>(
      '/schedule-uploads',
      fileForm(file),
      multipart,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not submit the schedule file.')
  }
}

export async function submitHrScheduleUpload(file: File): Promise<ScheduleUploadBatch[]> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleUploadBatch[]>>(
      '/schedule-uploads/hr-admin', fileForm(file), { ...multipart, params: hrModeParams },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not submit the HR schedule file.')
  }
}

export async function fetchMyScheduleUploads(): Promise<ScheduleUploadBatchSummary[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ScheduleUploadBatchSummary[]>>('/schedule-uploads/mine')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your schedule uploads.')
  }
}

export async function fetchMyScheduleUpload(batchId: string): Promise<ScheduleUploadBatch> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ScheduleUploadBatch>>(`/schedule-uploads/mine/${batchId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load the schedule upload.')
  }
}

export async function cancelMyScheduleUpload(batchId: string): Promise<ScheduleUploadBatchSummary> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleUploadBatchSummary>>(
      `/schedule-uploads/mine/${batchId}/cancel`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not cancel the schedule upload.')
  }
}

export async function fetchScheduleUploadsForReview(
  status: ScheduleUploadBatchStatus,
): Promise<ScheduleUploadBatchSummary[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ScheduleUploadBatchSummary[]>>(
      '/schedule-uploads/review',
      { params: { status } },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load schedule uploads for review.')
  }
}

export async function fetchScheduleUploadForReview(batchId: string): Promise<ScheduleUploadBatch> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ScheduleUploadBatch>>(`/schedule-uploads/review/${batchId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load the schedule upload.')
  }
}

export async function approveScheduleUpload(batchId: string, remarks: string): Promise<ScheduleUploadBatch> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleUploadBatch>>(
      `/schedule-uploads/review/${batchId}/approve`,
      { remarks: remarks.trim() || null },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not approve the schedule upload.')
  }
}

export async function rejectScheduleUpload(batchId: string, remarks: string): Promise<ScheduleUploadBatchSummary> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleUploadBatchSummary>>(
      `/schedule-uploads/review/${batchId}/reject`,
      { remarks },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not reject the schedule upload.')
  }
}

export async function fetchMyScheduleAssignments(): Promise<MyScheduleAssignment[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<MyScheduleAssignment[]>>('/my-schedule-assignments')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your schedule.')
  }
}
