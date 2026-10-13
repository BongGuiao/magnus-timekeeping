import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface RestDayPatternDay {
  pattern_id: string
  cycle_day_no: number
  is_workday: boolean
  schedule_template_id: string | null
}

export interface RestDayPattern {
  id: string
  pattern_code: string
  pattern_name: string
  cycle_length_days: number
  description: string | null
  is_active: boolean
  days: RestDayPatternDay[]
}

export interface RestDayPatternDayPayload {
  cycle_day_no: number
  is_workday: boolean
  schedule_template_id: string | null
}

export type RestDayPatternPayload = Omit<RestDayPattern, 'id' | 'days'> & {
  days: RestDayPatternDayPayload[]
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchRestDayPatterns(isActive: boolean | null = true): Promise<RestDayPattern[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<RestDayPattern[]>>('/rest-day-patterns/list', {
      params: isActive === null ? {} : { is_active: isActive },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load rest day patterns.')
  }
}

export async function createRestDayPattern(payload: RestDayPatternPayload): Promise<RestDayPattern> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<RestDayPattern>>('/rest-day-patterns', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create rest day pattern.')
  }
}

export async function updateRestDayPattern(
  patternId: string,
  payload: RestDayPatternPayload,
): Promise<RestDayPattern> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<RestDayPattern>>(
      `/rest-day-patterns/${patternId}`,
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update rest day pattern.')
  }
}

export async function deleteRestDayPattern(patternId: string): Promise<RestDayPattern> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<RestDayPattern>>(`/rest-day-patterns/${patternId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not delete rest day pattern.')
  }
}
