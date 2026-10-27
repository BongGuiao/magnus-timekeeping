import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { OrgUnit } from '../types/orgUnit'

export type OrgUnitWritePayload = Omit<
  OrgUnit,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
>

export interface OrgUnitType {
  company_id: string
  org_unit_type: string
  display_name: string
  sort_order: number
  is_default: boolean
  is_active: boolean
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchOrgUnits(companyId?: string): Promise<OrgUnit[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OrgUnit[]>>('/org-units/list', {
      params: companyId ? { company_id: companyId } : undefined,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load organization units.')
  }
}

export async function fetchOrgUnitTypes(companyId: string): Promise<OrgUnitType[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OrgUnitType[]>>('/org-units/types', {
      params: { company_id: companyId },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load organization unit types.')
  }
}

export async function fetchOrgUnit(orgUnitId: string): Promise<OrgUnit | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OrgUnit | null>>(`/org-units/${orgUnitId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load this organization unit.')
  }
}

export async function createOrgUnit(payload: OrgUnitWritePayload): Promise<OrgUnit> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OrgUnit>>('/org-units/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the organization unit.')
  }
}

export async function updateOrgUnit(orgUnitId: string, payload: OrgUnitWritePayload): Promise<OrgUnit> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<OrgUnit>>('/org-units/update', {
      ...payload,
      id: orgUnitId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the organization unit.')
  }
}
