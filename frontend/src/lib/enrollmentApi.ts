import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiSuccessEnvelope } from '../types/auth'
import type {
  EnrollmentResult, FaceEnrollmentReview, ResetFaceEnrollmentPayload, ResetFaceEnrollmentResult,
} from '../types/enrollment'

function enrollmentError(error: unknown, fallback: string): Error {
  if (error instanceof AxiosError) {
    const detail: unknown = error.response?.data?.detail
    if (typeof detail === 'string') return new Error(detail)
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((issue: unknown) =>
        typeof issue === 'object' && issue !== null && 'msg' in issue && typeof issue.msg === 'string'
          ? [issue.msg] : [])
      if (messages.length) return new Error(messages.join(' '))
    }
    return new Error(fallback)
  }
  return error instanceof Error ? error : new Error(fallback)
}

export async function fetchFaceEnrollment(employeeId: string): Promise<FaceEnrollmentReview> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<FaceEnrollmentReview>>(`/enrollment/employees/${employeeId}/samples`)
    return response.data.data
  } catch (error) {
    throw enrollmentError(error, 'Saved face samples could not be loaded.')
  }
}

export async function resetFaceEnrollment(employeeId: string, payload: ResetFaceEnrollmentPayload): Promise<ResetFaceEnrollmentResult> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ResetFaceEnrollmentResult>>(`/enrollment/employees/${employeeId}/reset`, payload)
    return response.data.data
  } catch (error) {
    throw enrollmentError(error, 'Face enrollment could not be reset.')
  }
}

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
    throw enrollmentError(err, 'Face enrollment failed. Please try again.')
  }
}
