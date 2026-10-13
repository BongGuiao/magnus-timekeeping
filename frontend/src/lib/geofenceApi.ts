import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { Geofence } from '../types/geofence'

export type GeofenceWritePayload = Omit<
  Geofence,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchGeofences(companyId?: string): Promise<Geofence[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Geofence[]>>('/geofences/list', {
      params: companyId ? { company_id: companyId } : undefined,
    })
    const geofences = response.data?.data
    if (!Array.isArray(geofences)) {
      throw new Error('The geofences API returned an invalid response.')
    }
    return geofences
  } catch (error) {
    return rethrowApiError(error, 'Could not load geofences.')
  }
}

export async function fetchGeofence(geofenceId: string): Promise<Geofence | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Geofence | null>>(`/geofences/${geofenceId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load this geofence.')
  }
}

export async function createGeofence(payload: GeofenceWritePayload): Promise<Geofence> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<Geofence>>('/geofences/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the geofence.')
  }
}

export async function updateGeofence(geofenceId: string, payload: GeofenceWritePayload): Promise<Geofence> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<Geofence>>('/geofences/update', {
      ...payload,
      id: geofenceId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the geofence.')
  }
}
