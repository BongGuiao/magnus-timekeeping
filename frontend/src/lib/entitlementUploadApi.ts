import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { EmployeeEntitlement, LeaveUnitType } from './leaveApi'

export type EntitlementUploadBalances = Pick<
  EmployeeEntitlement,
  | 'opening_minutes'
  | 'granted_minutes'
  | 'accrued_minutes'
  | 'carryover_minutes'
  | 'adjustment_minutes'
  | 'used_minutes'
  | 'reserved_minutes'
  | 'expired_minutes'
  | 'converted_minutes'
  | 'available_minutes'
>

export interface EntitlementUploadPreviewRow {
  row_no: number
  employee_no: string
  leave_code: string
  entitlement_year: number | null
  employee_name: string | null
  leave_name: string | null
  unit_type: LeaveUnitType | null
  action: 'CREATE' | 'UPDATE' | null
  errors: string[]
  before: EntitlementUploadBalances | null
  after: EntitlementUploadBalances | null
}

export interface EntitlementUploadPreview {
  is_valid: boolean
  error_count: number
  file_errors: string[]
  rows: EntitlementUploadPreviewRow[]
  preview_token: string | null
}

export interface EntitlementUploadResult {
  created: number
  updated: number
  employee_ids: string[]
  entitlement_ids: string[]
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as Partial<ApiErrorEnvelope> | undefined
    throw new Error(typeof body?.detail === 'string' ? body.detail : fallback)
  }
  throw error
}

function fileForm(file: File, previewToken?: string): FormData {
  const form = new FormData()
  form.append('file', file)
  if (previewToken) form.append('preview_token', previewToken)
  return form
}

const multipart = { headers: { 'Content-Type': 'multipart/form-data' } }

export async function downloadEntitlementUploadTemplate(): Promise<Blob> {
  try {
    const response = await apiClient.get<Blob>('/employee-entitlements/upload/template', { responseType: 'blob' })
    return response.data
  } catch (error) {
    return rethrowApiError(error, 'Could not download the entitlement template.')
  }
}

export async function previewEntitlementUpload(file: File): Promise<EntitlementUploadPreview> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EntitlementUploadPreview>>(
      '/employee-entitlements/upload/preview', fileForm(file), multipart,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not check the entitlement file.')
  }
}

export async function applyEntitlementUpload(file: File, previewToken: string): Promise<EntitlementUploadResult> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EntitlementUploadResult>>(
      '/employee-entitlements/upload', fileForm(file, previewToken), multipart,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not confirm the entitlement upload. Check the file again before retrying.')
  }
}
