import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface OperationalGroup {
  company_id: string
  operational_group: string
  display_name: string
  sort_order: number
  is_active: boolean
}

export type OperationalGroupUpdatePayload = Pick<OperationalGroup, 'display_name' | 'sort_order' | 'is_active'>

export const OPERATIONAL_GROUPS_CHANGED_EVENT = 'operational-groups-changed'

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchOperationalGroups(companyId: string, includeInactive = false): Promise<OperationalGroup[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OperationalGroup[]>>('/operational-groups/list', {
      params: { company_id: companyId, include_inactive: includeInactive },
    })
    const groups = response.data?.data
    if (!Array.isArray(groups)) {
      throw new Error('Invalid operational groups response: expected a JSON list. Check the deployed backend and Nginx API routing.')
    }
    return groups
  } catch (error) {
    return rethrowApiError(error, 'Could not load operational groups.')
  }
}

export async function createOperationalGroup(payload: OperationalGroup): Promise<OperationalGroup> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OperationalGroup>>('/operational-groups/create', payload)
    window.dispatchEvent(new Event(OPERATIONAL_GROUPS_CHANGED_EVENT))
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the operational group.')
  }
}

export async function updateOperationalGroup(
  companyId: string, code: string, payload: OperationalGroupUpdatePayload,
): Promise<OperationalGroup> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<OperationalGroup>>(
      `/operational-groups/${encodeURIComponent(code)}`, payload, { params: { company_id: companyId } },
    )
    window.dispatchEvent(new Event(OPERATIONAL_GROUPS_CHANGED_EVENT))
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the operational group.')
  }
}
