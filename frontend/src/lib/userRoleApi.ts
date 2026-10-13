import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface AvailableRole {
  id: string
  role_code: string
  role_name: string
  description: string | null
  scope_type: string
  is_system_role: boolean
  is_active: boolean
}

export interface UserRoleAssignment {
  id: string
  user_id: string
  role_id: string
  company_id: string | null
  org_unit_id: string | null
  effective_from: string
  effective_to: string | null
  assigned_by: string | null
}

export interface CreateUserRolePayload {
  user_id: string
  role_id: string
  company_id: string | null
  org_unit_id: string | null
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

function readList<T>(payload: unknown, endpoint: string): T[] {
  if (Array.isArray(payload)) return payload as T[]
  if (payload && typeof payload === 'object') {
    const data = (payload as { data?: unknown }).data
    if (Array.isArray(data)) return data as T[]
    if (data && typeof data === 'object' && Array.isArray((data as { data?: unknown }).data)) {
      return (data as { data: T[] }).data
    }
  }
  throw new Error(
    `${endpoint} returned an unexpected response. Check that the latest backend is running and returns a list in its success envelope.`,
  )
}

export async function fetchAvailableRoles(): Promise<AvailableRole[]> {
  try {
    const response = await apiClient.get<unknown>('/roles/list', {
      params: { is_active: true, limit: 1000 },
    })
    return readList<AvailableRole>(response.data, 'Roles endpoint')
  } catch (error) {
    return rethrowApiError(error, 'Could not load available roles.')
  }
}

export async function fetchUserRoleAssignments(userId: string): Promise<UserRoleAssignment[]> {
  try {
    const response = await apiClient.get<unknown>('/user-roles/list', {
      params: { user_id: userId, limit: 1000 },
    })
    return readList<UserRoleAssignment>(response.data, 'User roles endpoint')
  } catch (error) {
    return rethrowApiError(error, 'Could not load employee roles.')
  }
}

export async function createUserRoleAssignment(
  payload: CreateUserRolePayload,
): Promise<UserRoleAssignment> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<UserRoleAssignment>>(
      '/user-roles/create',
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not assign the role.')
  }
}

export async function updateUserRoleAssignment(
  assignmentId: string,
  payload: Partial<Pick<UserRoleAssignment, 'effective_to'>>,
): Promise<UserRoleAssignment> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<UserRoleAssignment>>('/user-roles/update', {
      id: assignmentId,
      ...payload,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the employee role.')
  }
}
