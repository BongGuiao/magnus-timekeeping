import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface PayrollCutoff {
  id: string
  payroll_group_id: string
  cutoff_code: string
  period_start: string
  period_end: string
  pay_date: string
  employee_review_deadline: string | null
  supervisor_deadline: string | null
  hr_deadline: string | null
  status: string
  locked_at: string | null
  locked_by: string | null
  calculation_version: string | null
  export_batch_id: string | null
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
  is_active: boolean
}

export type PayrollCutoffPayload = Omit<
  PayrollCutoff,
  | 'id'
  | 'locked_at'
  | 'locked_by'
  | 'created_at'
  | 'created_by'
  | 'updated_at'
  | 'updated_by'
  | 'row_version'
>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchPayrollCutoffs(payrollGroupId?: string): Promise<PayrollCutoff[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<PayrollCutoff[]>>('/payroll-cutoffs/list', {
      params: { ...(payrollGroupId ? { payroll_group_id: payrollGroupId } : {}), limit: 1000 },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load payroll cutoffs.')
  }
}

export async function createPayrollCutoff(payload: PayrollCutoffPayload): Promise<PayrollCutoff> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<PayrollCutoff>>('/payroll-cutoffs/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the payroll cutoff.')
  }
}

export async function updatePayrollCutoff(
  cutoffId: string,
  payload: PayrollCutoffPayload,
): Promise<PayrollCutoff> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<PayrollCutoff>>('/payroll-cutoffs/update', {
      ...payload,
      id: cutoffId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the payroll cutoff.')
  }
}
