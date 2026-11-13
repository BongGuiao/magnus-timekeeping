import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { Employee } from '../types/employee'
import type {
  PersonalDetails, PersonalDetailsPayload, PersonalDetailsImportRow, PersonalDetailsImportResult,
} from './employeePersonalDetails'

export const EMPLOYEE_CREATED_EVENT = 'employee-created'

export type EmployeeWritePayload = Omit<
  Employee,
  'id' | 'created_at' | 'created_by' | 'updated_at' | 'updated_by' | 'row_version'
> & { personal_details?: PersonalDetailsPayload }

function rethrowApiError(error: unknown, fallback: string): never {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorEnvelope | undefined
    throw new Error(body?.detail ?? fallback)
  }

  throw error
}

export async function exportEmployeesCsv(): Promise<Blob> {
  try {
    const response = await apiClient.get<Blob>('/employees/export', {
      params: { dashboard_role_code: 'HR_ADMIN' },
      responseType: 'blob',
    })
    const contentType = response.headers['content-type']
    if (typeof contentType !== 'string' || !contentType.startsWith('text/csv')) {
      throw new Error('The employee export server did not return a CSV file.')
    }
    return response.data
  } catch (error) {
    if (error instanceof AxiosError) {
      const data: unknown = error.response?.data
      if (data instanceof Blob) {
        let body: unknown
        try { body = JSON.parse(await data.text()) }
        catch (parseError) { if (!(parseError instanceof SyntaxError)) throw parseError }
        if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
          throw new Error(body.detail)
        }
      }
      throw new Error('Could not export employees. Check your access and connection, then try again.')
    }
    throw error
  }
}

export async function fetchEmployeePersonalDetails(employeeId: string): Promise<PersonalDetails | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<PersonalDetails | null>>(`/employees/${employeeId}/personal-details`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load employee personal information.')
  }
}

export async function fetchPersonalDetailsTemplateExample(): Promise<PersonalDetailsImportRow | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<PersonalDetailsImportRow | null>>('/employees/personal-details/template-example')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load an employee example for the template.')
  }
}

export async function importEmployeePersonalDetails(
  rows: PersonalDetailsImportRow[], preview: boolean,
): Promise<PersonalDetailsImportResult[]> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<PersonalDetailsImportResult[]>>(
      '/employees/personal-details/import', { rows, preview },
    )
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not import employee personal information.')
  }
}

export async function fetchEmployees(): Promise<Employee[]> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Employee[]>>('/employees/list')
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load employees.')
  }
}

export async function fetchEmployee(employeeId: string): Promise<Employee | null> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<Employee | null>>(`/employees/${employeeId}`)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not load this employee.')
  }
}

export async function createEmployee(payload: EmployeeWritePayload): Promise<Employee> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<Employee>>('/employees/create', payload)
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not create the employee.')
  }
}

export async function updateEmployee(employeeId: string, payload: EmployeeWritePayload): Promise<Employee> {
  try {
    const response = await apiClient.put<ApiSuccessEnvelope<Employee>>('/employees/update', {
      ...payload,
      id: employeeId,
    })
    return response.data.data
  } catch (error) {
    return rethrowApiError(error, 'Could not update the employee.')
  }
}
