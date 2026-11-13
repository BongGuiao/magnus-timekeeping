import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiSuccessEnvelope } from '../types/auth'
import type {
  EnrollmentResult, FaceEnrollmentReview, ResetFaceEnrollmentPayload, ResetFaceEnrollmentResult, SimilarityOverride,
} from '../types/enrollment'

export class FaceSimilarityConflictError extends Error {
  conflictingEmployeeNos: string[]
  closestDistance: number | null
  threshold: number | null

  constructor(message: string, conflictingEmployeeNos: string[], closestDistance: number | null, threshold: number | null) {
    super(message)
    this.name = 'FaceSimilarityConflictError'
    this.conflictingEmployeeNos = conflictingEmployeeNos
    this.closestDistance = closestDistance
    this.threshold = threshold
  }
}

function enrollmentError(error: unknown, fallback: string): Error {
  if (error instanceof AxiosError) {
    const data: unknown = error.response?.data
    const detail: unknown = typeof data === 'object' && data !== null && 'detail' in data ? data.detail : undefined
    if (typeof data === 'object' && data !== null && 'code' in data && data.code === 'FACE_SIMILARITY_CONFLICT'
      && 'conflicting_employee_nos' in data && Array.isArray(data.conflicting_employee_nos) && typeof detail === 'string') {
      const numbers = data.conflicting_employee_nos.filter((value: unknown): value is string => typeof value === 'string')
      const distance = 'closest_distance' in data && typeof data.closest_distance === 'number' ? data.closest_distance : null
      const threshold = 'threshold' in data && typeof data.threshold === 'number' ? data.threshold : null
      return new FaceSimilarityConflictError(detail, numbers, distance, threshold)
    }
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
export async function enrollFace(file: File, employeeId: string, override?: SimilarityOverride): Promise<EnrollmentResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('employee_id', String(employeeId))
  if (override) {
    formData.append('similarity_override_employee_nos', override.conflicting_employee_nos.join(','))
    formData.append('similarity_override_reason', override.reason)
  }

  try {
    const response = await apiClient.post<ApiSuccessEnvelope<EnrollmentResult>>('/enrollment/face', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data.data
  } catch (err) {
    throw enrollmentError(err, 'Face enrollment failed. Please try again.')
  }
}
