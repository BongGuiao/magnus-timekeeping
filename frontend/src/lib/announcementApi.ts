import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface ManagedAnnouncement {
  id: string
  title: string
  body: string
  company_id: string | null
  posted_at: string
  is_active: boolean
  effective_from: string
  effective_to: string | null
}

export interface AnnouncementPayload {
  title: string
  body: string
  company_id: string | null
  is_active: boolean
  effective_from: string
  effective_to: string | null
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchManagedAnnouncements(): Promise<ManagedAnnouncement[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<ManagedAnnouncement[]>>('/announcements/manage/list')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load announcements.')
  }
}

export async function createAnnouncement(payload: AnnouncementPayload): Promise<ManagedAnnouncement> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ManagedAnnouncement>>('/announcements/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the announcement.')
  }
}

export async function updateAnnouncement(id: string, payload: AnnouncementPayload): Promise<ManagedAnnouncement> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<ManagedAnnouncement>>('/announcements/update', {
      ...payload,
      id,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the announcement.')
  }
}
