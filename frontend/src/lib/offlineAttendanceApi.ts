import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiSuccessEnvelope } from '../types/auth'

export interface OfflineReviewEvent {
  event_id: string
  user_id: string
  action: string
  captured_at: string
  received_at: string
  reason: string | null
  payload: { latitude: number; longitude: number; accuracy: number; device_uuid: string }
}

function rethrow(error: unknown): never {
  if (error instanceof AxiosError) {
    throw new Error(typeof error.response?.data?.detail === 'string'
      ? error.response.data.detail : 'Offline attendance review could not reach the server.')
  }
  throw error
}

export async function fetchOfflineReviewEvents(): Promise<OfflineReviewEvent[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OfflineReviewEvent[]>>('/attendance/offline/events', {
      params: { review: true, limit: 50 },
    })
    return response.data.data
  } catch (error) {
    return rethrow(error)
  }
}

export async function reviewOfflineEvent(eventId: string, notes: string): Promise<void> {
  try {
    await apiClient.post(`/attendance/offline/events/${eventId}/review`, { notes })
  } catch (error) {
    rethrow(error)
  }
}
