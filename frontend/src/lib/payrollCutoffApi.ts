import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface PayrollCutoff {
  id: string
  payroll_group_id: string
  cutoff_code: string
  cutoff_half: 'FIRST_HALF' | 'SECOND_HALF' | null
  period_start: string
  period_end: string
  pay_date: string
  attendance_deadline: string | null
  attendance_finalized_at?: string | null
  attendance_finalized_by?: string | null
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

export interface EmployeeCutoffResult {
  id: string
  cutoff_id: string
  cutoff_code: string | null
  period_start: string | null
  period_end: string | null
  employee_id: string
  employee_name: string | null
  operational_group: string | null
  attendance_finalized_at: string | null
  cutoff_locked_at: string | null
  scheduled_days: number
  paid_days: number
  regular_minutes: number
  late_minutes: number
  undertime_minutes: number
  absence_minutes: number
  paid_leave_minutes: number
  unpaid_leave_minutes: number
  ordinary_ot_minutes: number
  rest_day_minutes: number
  rest_day_ot_minutes: number
  special_day_minutes: number
  special_day_ot_minutes: number
  holiday_minutes: number
  holiday_ot_minutes: number
  night_regular_minutes: number
  night_ot_minutes: number
  official_business_minutes: number
  exception_count: number
  payroll_status: string
  calculated_at: string | null
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
    const body = error.response?.data as (Omit<ApiErrorEnvelope, 'detail'> & { detail?: unknown }) | undefined
    const status = error.response?.status
    const detail = body?.detail
    const validationMessages = Array.isArray(detail)
      ? detail.flatMap((item: unknown) => {
        if (typeof item !== 'object' || item === null || !('msg' in item)) return []
        const message = item.msg
        if (typeof message !== 'string') return []
        const location = 'loc' in item && Array.isArray(item.loc)
          ? item.loc.filter(
            (part): part is string | number => typeof part === 'string' || typeof part === 'number',
          )
          : []
        return [`${location.length ? `${location.join(' → ')}: ` : ''}${message}`]
      })
      : []
    const message = typeof detail === 'string'
      ? detail
      : validationMessages.length
        ? validationMessages.join('; ')
        : fallback
    if (status && status >= 500) {
      throw new Error(
        `${message} (HTTP ${status}). Check the backend logs and confirm ` +
        '`payroll.employee_cutoff_results` includes `official_business_minutes`; ' +
        'apply `backend/sql/20261014_add_official_business_minutes_to_employee_cutoff_results.sql` if needed.',
      )
    }
    if (status) {
      throw new Error(`${message} (HTTP ${status}).`)
    }
    throw new Error(`${message} ${error.message}`)
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

export async function calculatePayrollCutoff(cutoffId: string): Promise<EmployeeCutoffResult[]> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmployeeCutoffResult[]>>(
      `/payroll-cutoffs/${encodeURIComponent(cutoffId)}/calculate`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not calculate payroll cutoff results.')
  }
}

export async function fetchPayrollCutoffResults(cutoffId: string): Promise<EmployeeCutoffResult[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeCutoffResult[]>>(
      `/payroll-cutoffs/${encodeURIComponent(cutoffId)}/results`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load payroll cutoff results.')
  }
}

export async function fetchMyPayrollCutoffResults(): Promise<EmployeeCutoffResult[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeCutoffResult[]>>(
      '/payroll-cutoffs/results/mine',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your payroll cutoff results.')
  }
}

export async function fetchMyTeamPayrollCutoffResults(): Promise<EmployeeCutoffResult[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeCutoffResult[]>>(
      '/payroll-cutoffs/results/team',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load your team payroll cutoff results.')
  }
}

export async function fetchOrganizationPayrollCutoffResults(): Promise<EmployeeCutoffResult[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeCutoffResult[]>>(
      '/payroll-cutoffs/results/organization',
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load organization payroll cutoff results.')
  }
}
