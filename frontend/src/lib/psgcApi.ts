import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope } from '../types/auth'
import type { PsgcPlace } from '../types/psgc'

function rethrowPsgcError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

async function fetchPlaces(path: string, fallback: string): Promise<PsgcPlace[]> {
  try {
    const response = await apiClient.get<PsgcPlace[]>(`/psgc/${path}`)
    if (!Array.isArray(response.data)) {
      throw new Error('The geographic reference API returned an invalid response.')
    }
    return response.data
  } catch (error) {
    return rethrowPsgcError(error, fallback)
  }
}

export function fetchPsgcRegions(): Promise<PsgcPlace[]> {
  return fetchPlaces('regions', 'Could not load Philippine regions.')
}

export function fetchPsgcProvinces(regionCode: string): Promise<PsgcPlace[]> {
  return fetchPlaces(
    `regions/${encodeURIComponent(regionCode)}/provinces`,
    'Could not load provinces.',
  )
}

export function fetchPsgcProvinceCities(provinceCode: string): Promise<PsgcPlace[]> {
  return fetchPlaces(
    `provinces/${encodeURIComponent(provinceCode)}/cities-municipalities`,
    'Could not load cities and municipalities.',
  )
}

export function fetchPsgcRegionCities(regionCode: string): Promise<PsgcPlace[]> {
  return fetchPlaces(
    `regions/${encodeURIComponent(regionCode)}/cities-municipalities`,
    'Could not load cities and municipalities.',
  )
}

export function fetchPsgcBarangays(cityCode: string): Promise<PsgcPlace[]> {
  return fetchPlaces(
    `cities-municipalities/${encodeURIComponent(cityCode)}/barangays`,
    'Could not load barangays.',
  )
}
