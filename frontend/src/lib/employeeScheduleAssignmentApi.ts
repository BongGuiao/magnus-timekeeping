import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'

export interface EmployeeScheduleAssignment {
  id: string
  employee_id: string
  schedule_template_id: string
  rest_day_pattern_id: string | null
  assignment_type: string
  effective_from: string
  effective_to: string | null
  reason: string | null
  approved_by: string | null
  approved_at: string | null
  status: string
  created_at: string | null
  created_by: string | null
  updated_at: string | null
  updated_by: string | null
  row_version: number | null
  is_active: boolean
}

export interface EmployeeScheduleAssignmentPayload {
  employee_id: string
  schedule_template_id: string
  rest_day_pattern_id: string | null
  assignment_type: string
  effective_from: string
  effective_to: string | null
  reason: string | null
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchEmployeeScheduleAssignments(employeeId: string): Promise<EmployeeScheduleAssignment[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeScheduleAssignment[]>>(
      '/employee-schedule-assignments/list',
      { params: { employee_id: employeeId } },
    )
    if (!Array.isArray(response.data.data)) {
      throw new Error('Employee schedule assignments endpoint returned an invalid list response.')
    }
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load employee schedule assignments.')
  }
}

export async function createEmployeeScheduleAssignment(
  payload: EmployeeScheduleAssignmentPayload,
): Promise<EmployeeScheduleAssignment> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmployeeScheduleAssignment>>(
      '/employee-schedule-assignments/create',
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create employee schedule assignment.')
  }
}

export async function updateEmployeeScheduleAssignment(
  assignmentId: string,
  payload: Partial<EmployeeScheduleAssignmentPayload>,
): Promise<EmployeeScheduleAssignment> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<EmployeeScheduleAssignment>>(
      `/employee-schedule-assignments/${assignmentId}`,
      payload,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update employee schedule assignment.')
  }
}

export async function approveEmployeeScheduleAssignment(
  assignmentId: string,
): Promise<EmployeeScheduleAssignment> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmployeeScheduleAssignment>>(
      `/employee-schedule-assignments/${assignmentId}/approve`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not approve employee schedule assignment.')
  }
}

export async function deactivateEmployeeScheduleAssignment(
  assignmentId: string,
): Promise<EmployeeScheduleAssignment> {
  try {
    const response = await apiClient.delete<ApiSuccessEnvelope<EmployeeScheduleAssignment>>(
      `/employee-schedule-assignments/${assignmentId}`,
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not deactivate employee schedule assignment.')
  }
}
