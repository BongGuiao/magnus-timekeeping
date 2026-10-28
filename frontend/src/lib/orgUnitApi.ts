import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { OrgUnit } from '../types/orgUnit'

export type OrgUnitWritePayload = Omit<
  OrgUnit,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version' | 'deleted_at' | 'deleted_by'
>

export interface OrgUnitType {
  company_id: string
  org_unit_type: string
  display_name: string
  sort_order: number
  is_default: boolean
  is_active: boolean
  deleted_at?: string | null
  deleted_by?: string | null
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchOrgUnits(companyId?: string, includeDeleted = false): Promise<OrgUnit[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OrgUnit[]>>('/org-units/list', {
      params: {
        ...(companyId ? { company_id: companyId } : {}),
        include_deleted: includeDeleted,
      },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load organization units.')
  }
}

export async function fetchOrgUnitTypes(
  companyId: string,
  includeInactive = false,
  includeDeleted = false,
): Promise<OrgUnitType[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<OrgUnitType[]>>('/org-units/types', {
      params: {
        company_id: companyId,
        include_inactive: includeInactive,
        include_deleted: includeDeleted,
      },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load organization unit types.')
  }
}

export type OrgUnitTypeCreatePayload = Omit<
  OrgUnitType,
  'company_id' | 'deleted_at' | 'deleted_by'
> & { company_id: string }
export type OrgUnitTypeUpdatePayload = Pick<
  OrgUnitType,
  'display_name' | 'sort_order' | 'is_default' | 'is_active'
>

export async function createOrgUnitType(
  payload: OrgUnitTypeCreatePayload,
): Promise<OrgUnitType> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<OrgUnitType>>(
      '/org-units/types/create',
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the organization unit type.')
  }
}

export async function updateOrgUnitType(
  companyId: string,
  orgUnitType: string,
  payload: OrgUnitTypeUpdatePayload,
): Promise<OrgUnitType> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<OrgUnitType>>(
      `/org-units/types/${encodeURIComponent(orgUnitType)}`,
      payload,
      { params: { company_id: companyId } },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the organization unit type.')
  }
}

export async function deleteOrgUnitType(
  companyId: string,
  orgUnitType: string,
): Promise<OrgUnitType> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<OrgUnitType>>(
      `/org-units/types/${encodeURIComponent(orgUnitType)}`,
      { params: { company_id: companyId } },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not delete the organization unit type.')
  }
}

export async function deleteOrgUnit(orgUnitId: string): Promise<OrgUnit> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<OrgUnit>>(`/org-units/${orgUnitId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not delete the organization unit.')
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
