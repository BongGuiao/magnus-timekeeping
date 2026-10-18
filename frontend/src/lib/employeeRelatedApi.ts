import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type {
  EmployeeSkill,
  EmployeeSkillWritePayload,
  EmploymentAssignment,
  EmploymentAssignmentWritePayload,
} from '../types/employeeRelated'

export const EMPLOYMENT_ASSIGNMENT_CHANGED_EVENT = 'employment-assignment-changed'

export function isCurrentEmploymentAssignment(assignment: EmploymentAssignment, today = getManilaDate()): boolean {
  return assignment.is_active
    && assignment.status === 'ACTIVE'
    && assignment.effective_from <= today
    && (!assignment.effective_to || assignment.effective_to >= today)
    && (!assignment.separation_date || assignment.separation_date >= today)
}

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }
  throw error
}

export async function fetchEmploymentAssignments(employeeId: string): Promise<EmploymentAssignment[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmploymentAssignment[]>>('/employment-assignments/list', {
      params: { employee_id: employeeId },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load employment assignments.')
  }
}

export async function fetchCurrentEmploymentAssignment(employeeId: string): Promise<EmploymentAssignment | null> {
  const assignments = await fetchCurrentEmploymentAssignments(employeeId)
  return assignments[0] ?? null
}

export async function fetchCurrentEmploymentAssignmentWithPrimaryLocation(
  employeeId: string,
): Promise<EmploymentAssignment | null> {
  const assignments = await fetchCurrentEmploymentAssignments(employeeId)
  return assignments.find((assignment) => assignment.primary_location_id !== null) ?? null
}

export async function fetchCurrentEmploymentAssignments(employeeId: string): Promise<EmploymentAssignment[]> {
  const assignments = await fetchEmploymentAssignments(employeeId)
  return assignments.filter((assignment) => isCurrentEmploymentAssignment(assignment))
}

export function getManilaDate(asOf = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Manila',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(asOf)
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${values.year}-${values.month}-${values.day}`
}

export function getCompletedServiceMonths(hireDate: string, asOf = new Date()): number {
  const today = getManilaDate(asOf)
  const [hireYear, hireMonth, hireDay] = hireDate.split('-').map(Number)
  const [todayYear, todayMonth, todayDay] = today.split('-').map(Number)
  let months = (todayYear - hireYear) * 12 + todayMonth - hireMonth
  if (todayDay < hireDay) months -= 1
  return Math.max(0, months)
}

export async function createEmploymentAssignment(payload: EmploymentAssignmentWritePayload): Promise<EmploymentAssignment> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmploymentAssignment>>('/employment-assignments/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the employment assignment.')
  }
}

export async function updateEmploymentAssignment(
  assignmentId: string,
  payload: EmploymentAssignmentWritePayload,
): Promise<EmploymentAssignment> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<EmploymentAssignment>>('/employment-assignments/update', {
      ...payload,
      id: assignmentId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the employment assignment.')
  }
}

export async function fetchEmployeeSkills(employeeId: string): Promise<EmployeeSkill[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<EmployeeSkill[]>>('/employee-skills/list', {
      params: { employee_id: employeeId },
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load employee skills.')
  }
}

export async function createEmployeeSkill(payload: EmployeeSkillWritePayload): Promise<EmployeeSkill> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EmployeeSkill>>('/employee-skills/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the employee skill.')
  }
}

export async function updateEmployeeSkill(skillId: string, payload: EmployeeSkillWritePayload): Promise<EmployeeSkill> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<EmployeeSkill>>('/employee-skills/update', {
      ...payload,
      id: skillId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the employee skill.')
  }
}
