import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export type HolidayCalendarStatus = 'DRAFT' | 'PUBLISHED' | 'CLOSED'
export type HolidayStatus = 'ACTIVE' | 'CANCELLED' | 'SUPERSEDED'
export type HolidayType = 'REGULAR' | 'SPECIAL_NONWORKING' | 'SPECIAL_WORKING' | 'LOCAL' | 'COMPANY'

export interface HolidayCalendar {
  id: string
  company_id: string
  calendar_code: string
  calendar_name: string
  effective_year: number
  province: string | null
  city: string | null
  status: HolidayCalendarStatus
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  row_version: number | null
  is_active: boolean
}

export type HolidayCalendarPayload = Omit<
  HolidayCalendar,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
>

export interface Holiday {
  id: string
  holiday_calendar_id: string
  holiday_date: string
  holiday_name: string
  holiday_type: HolidayType
  is_double_holiday: boolean
  pay_rule_code: string | null
  source_reference: string | null
  status: HolidayStatus
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  row_version: number | null
  is_active: boolean
}

export type HolidayPayload = Omit<
  Holiday,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchHolidayCalendars(companyId: string, effectiveYear: number): Promise<HolidayCalendar[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<HolidayCalendar[]>>('/holiday-calendars/list', {
      params: { company_id: companyId, effective_year: effectiveYear },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load calendars for the selected company.')
  }
}

export async function createHolidayCalendar(payload: HolidayCalendarPayload): Promise<HolidayCalendar> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<HolidayCalendar>>('/holiday-calendars/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the calendar.')
  }
}

export async function updateHolidayCalendar(id: string, payload: HolidayCalendarPayload): Promise<HolidayCalendar> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<HolidayCalendar>>('/holiday-calendars/update', {
      ...payload,
      id,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the calendar.')
  }
}

export async function fetchHolidays(calendarId: string): Promise<Holiday[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Holiday[]>>('/holidays/list', {
      params: { holiday_calendar_id: calendarId },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load dates for the selected calendar.')
  }
}

export async function createHoliday(payload: HolidayPayload): Promise<Holiday> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<Holiday>>('/holidays/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the calendar date.')
  }
}

export async function updateHoliday(id: string, payload: HolidayPayload): Promise<Holiday> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<Holiday>>('/holidays/update', {
      ...payload,
      id,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the calendar date.')
  }
}
