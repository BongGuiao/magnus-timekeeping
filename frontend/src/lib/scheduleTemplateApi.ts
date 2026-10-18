import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export type ScheduleType =
  | 'FIXED'
  | 'FLEXIBLE'
  | 'SHIFTING'
  | 'OVERNIGHT'
  | 'SPLIT'
  | 'COMPRESSED'
  | 'FIELD'
  | 'ON_CALL'

export interface ScheduleTemplate {
  id: string
  company_id: string
  schedule_code: string
  schedule_name: string
  schedule_type: ScheduleType
  required_minutes: number
  grace_minutes: number
  grace_method: string
  is_overnight: boolean
  ot_eligible: boolean
  pre_shift_ot_allowed: boolean
  minimum_ot_minutes: number
  holiday_calendar_id: string | null
  effective_from: string
  effective_to: string | null
  status: string
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  row_version: number | null
  is_active: boolean
}

export type ScheduleTemplatePayload = Omit<
  ScheduleTemplate,
  | 'id'
  | 'created_at'
  | 'created_by'
  | 'updated_at'
  | 'updated_by'
  | 'row_version'
>

export type ScheduleSegmentType = 'WORK' | 'PAID_BREAK' | 'UNPAID_BREAK'
export type BreakSlot = 'FIRST_BREAK' | 'MEAL_BREAK' | 'SECOND_BREAK' | 'OT_BREAK'

export interface ScheduleSegment {
  id: string
  schedule_template_id: string
  segment_sequence: number
  segment_type: ScheduleSegmentType
  start_time: string
  end_time: string
  end_day_offset: number
  paid_minutes: number
  punch_required: boolean
  auto_deduct: boolean
  flex_start_minutes: number
  break_slot: BreakSlot | null
  work_segment_sequence: number | null
  break_minutes: number
}

export type ScheduleSegmentPayload = Omit<ScheduleSegment, 'id' | 'schedule_template_id'>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchScheduleSegments(templateId: string): Promise<ScheduleSegment[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ScheduleSegment[]>>(
      `/schedule-templates/${templateId}/segments`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load schedule segments.')
  }
}

export async function createScheduleSegment(
  templateId: string,
  payload: ScheduleSegmentPayload,
): Promise<ScheduleSegment> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleSegment>>(
      `/schedule-templates/${templateId}/segments`,
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the schedule segment.')
  }
}

export async function updateScheduleSegment(
  templateId: string,
  segmentId: string,
  payload: Partial<ScheduleSegmentPayload>,
): Promise<ScheduleSegment> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<ScheduleSegment>>(
      `/schedule-templates/${templateId}/segments/${segmentId}`,
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the schedule segment.')
  }
}

export async function deleteScheduleSegment(templateId: string, segmentId: string): Promise<ScheduleSegment> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<ScheduleSegment>>(
      `/schedule-templates/${templateId}/segments/${segmentId}`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not delete the schedule segment.')
  }
}

export async function fetchScheduleTemplates(filters: {
  companyId?: string
  scheduleType?: ScheduleType
  status?: string
  isActive?: boolean
} = {}): Promise<ScheduleTemplate[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ScheduleTemplate[]>>('/schedule-templates/list', {
      params: {
        ...(filters.companyId ? { company_id: filters.companyId } : {}),
        ...(filters.scheduleType ? { schedule_type: filters.scheduleType } : {}),
        ...(filters.status ? { template_status: filters.status } : {}),
        ...(filters.isActive === undefined ? {} : { is_active: filters.isActive }),
        limit: 1000,
      },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load schedule templates.')
  }
}

export async function createScheduleTemplate(payload: ScheduleTemplatePayload): Promise<ScheduleTemplate> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ScheduleTemplate>>('/schedule-templates/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the schedule template.')
  }
}

export async function updateScheduleTemplate(
  templateId: string,
  payload: ScheduleTemplatePayload,
): Promise<ScheduleTemplate> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<ScheduleTemplate>>('/schedule-templates/update', {
      ...payload,
      id: templateId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the schedule template.')
  }
}

export async function deactivateScheduleTemplate(templateId: string): Promise<ScheduleTemplate> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<ScheduleTemplate>>(`/schedule-templates/${templateId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not deactivate the schedule template.')
  }
}
