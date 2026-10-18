import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export type PayrollPayFrequency = 'WEEKLY' | 'BIWEEKLY' | 'SEMIMONTHLY' | 'MONTHLY'
export type PayrollRateType = 'MONTHLY' | 'DAILY' | 'HOURLY'

export interface PayrollGroup {
  id: string
  company_id: string
  payroll_group_code: string
  payroll_group_name: string
  pay_frequency: PayrollPayFrequency
  rate_type: PayrollRateType
  standard_minutes_per_day: number
  annual_divisor: number | null
  rounding_minutes: number
  holiday_calendar_id: string | null
  status: string
  created_at: string
  created_by: string | null
  updated_at: string
  updated_by: string | null
  row_version: number
  is_active: boolean
}

export type PayrollGroupPayload = Omit<
  PayrollGroup,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
>

export interface HolidayCalendarOption {
  id: string
  company_id: string
  calendar_code: string
  calendar_name: string
  effective_year: number
  status: string
  is_active: boolean
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchPayrollGroups(companyId?: string): Promise<PayrollGroup[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<PayrollGroup[]>>('/payroll-groups/list', {
      params: { ...(companyId ? { company_id: companyId } : {}), limit: 1000 },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load payroll groups.')
  }
}

export async function fetchPayrollHolidayCalendars(companyId: string): Promise<HolidayCalendarOption[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<HolidayCalendarOption[]>>('/holiday-calendars/list', {
      params: { company_id: companyId },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load holiday calendars.')
  }
}

export async function createPayrollGroup(payload: PayrollGroupPayload): Promise<PayrollGroup> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<PayrollGroup>>('/payroll-groups/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the payroll group.')
  }
}

export async function updatePayrollGroup(
  groupId: string,
  payload: PayrollGroupPayload,
): Promise<PayrollGroup> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<PayrollGroup>>('/payroll-groups/update', {
      ...payload,
      id: groupId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the payroll group.')
  }
}
