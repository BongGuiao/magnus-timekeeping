import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/auth'
import type { EnrollmentResult } from '../types/enrollment'

// Relative path: nginx proxies /enrollment/* to the FastAPI backend (see nginx/default.conf).
export async function enrollFace(file: File, employeeId: string): Promise<EnrollmentResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('employee_id', String(employeeId))

  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EnrollmentResult>>('/enrollment/face', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data.data
  } catch (err) {
    if (err instanceof AxiosError) {
      const body = err.response?.data as ApiErrorEnvelope | undefined
      throw new Error(body?.detail ?? 'Face enrollment failed. Please try again.')
    }
    throw err
  }
}
