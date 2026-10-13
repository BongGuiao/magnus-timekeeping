import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { Location } from '../types/location'

export type LocationWritePayload = Omit<
  Location,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchLocations(companyId?: string): Promise<Location[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Location[]>>('/locations/list', {
      params: companyId ? { company_id: companyId } : undefined,
    })
    const locations = response.data?.data
    if (!Array.isArray(locations)) {
      throw new Error('The locations API returned an invalid response.')
    }
    return locations
  } catch (error) {
    return rethrowApiError(error, 'Could not load locations.')
  }
}

export async function fetchLocation(locationId: string): Promise<Location | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Location | null>>(`/locations/${locationId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load this location.')
  }
}

export async function createLocation(payload: LocationWritePayload): Promise<Location> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<Location>>('/locations/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the location.')
  }
}

export async function updateLocation(locationId: string, payload: LocationWritePayload): Promise<Location> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<Location>>('/locations/update', {
      ...payload,
      id: locationId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the location.')
  }
}
