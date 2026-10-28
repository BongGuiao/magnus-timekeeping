import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { Location, LocationType } from '../types/location'

export type LocationWritePayload = Omit<
  Location,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version' | 'deleted_at' | 'deleted_by'
>

export interface LocationTypeOption {
  company_id: string
  location_type: LocationType
  display_name: string
  sort_order: number
  is_default: boolean
  is_active: boolean
  deleted_at?: string | null
  deleted_by?: string | null
}

export type LocationTypeCreatePayload = Omit<
  LocationTypeOption,
  'company_id' | 'deleted_at' | 'deleted_by'
> & {
  company_id: string
}
export type LocationTypeUpdatePayload = Pick<
  LocationTypeOption,
  'display_name' | 'sort_order' | 'is_default' | 'is_active'
>

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchLocationTypes(
  companyId: string,
  includeInactive = false,
  includeDeleted = false,
): Promise<LocationTypeOption[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<LocationTypeOption[]>>('/locations/types', {
      params: {
        company_id: companyId,
        include_inactive: includeInactive,
        include_deleted: includeDeleted,
      },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load location types.')
  }
}

export async function createLocationType(
  payload: LocationTypeCreatePayload,
): Promise<LocationTypeOption> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<LocationTypeOption>>(
      '/locations/types/create',
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the location type.')
  }
}

export async function updateLocationType(
  companyId: string,
  locationType: string,
  payload: LocationTypeUpdatePayload,
): Promise<LocationTypeOption> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<LocationTypeOption>>(
      `/locations/types/${encodeURIComponent(locationType)}`,
      payload,
      { params: { company_id: companyId } },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the location type.')
  }
}

export async function deleteLocationType(
  companyId: string,
  locationType: string,
): Promise<LocationTypeOption> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<LocationTypeOption>>(
      `/locations/types/${encodeURIComponent(locationType)}`,
      { params: { company_id: companyId } },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not delete the location type.')
  }
}

export async function fetchLocations(companyId?: string, includeDeleted = false): Promise<Location[]> {
  try {
    const params: Record<string, string | boolean> = {}
    if (companyId) params.company_id = companyId
    if (includeDeleted) params.include_deleted = true
    const response = await apiClient.get<ApiSuccessEnvelope<Location[]>>('/locations/list', { params })
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

export async function deleteLocation(locationId: string): Promise<Location> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<Location>>(`/locations/${locationId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not delete the location.')
  }
}
