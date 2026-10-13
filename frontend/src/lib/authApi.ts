import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type {
  ApiErrorEnvelope,
  ApiSuccessEnvelope,
  ChangePasswordRequest,
  ChangePasswordResult,
  LoginRequest,
  TokenResponse,
  UserSummary,
} from '../types/auth'

// Relative path: nginx proxies /auth/* to the FastAPI backend (see nginx/default.conf).
export async function loginRequest(payload: LoginRequest): Promise<TokenResponse> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<TokenResponse>>('/auth/login', payload)
    return response.data.data
  } catch (err) {
    if (err instanceof AxiosError) {
      const body = err.response?.data as ApiErrorEnvelope | undefined
      throw new Error(body?.detail ?? 'Login failed. Please try again.')
    }
    throw err
  }
}

export async function searchUserByEmployeeCode(employeeCode: string): Promise<UserSummary> {
  try {
    const response = await apiClient.get<ApiSuccessEnvelope<UserSummary>>('/auth/users/search', {
      params: { employee_code: employeeCode },
    })
    return response.data.data
  } catch (err) {
    if (err instanceof AxiosError) {
      const body = err.response?.data as ApiErrorEnvelope | undefined
      throw new Error(body?.detail ?? 'Employee code could not be verified.')
    }
    throw err
  }
}

// FastAPI returns a string for rule failures but a list of issues for request validation failures.
function formatErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue) => (typeof issue === 'object' && issue !== null && 'msg' in issue ? String(issue.msg) : ''))
      .filter(Boolean)
    if (messages.length > 0) return messages.join(' ')
  }
  return fallback
}

export async function changePassword(payload: ChangePasswordRequest): Promise<ChangePasswordResult> {
  try {
    const response = await apiClient.post<ApiSuccessEnvelope<ChangePasswordResult>>('/auth/change-password', payload)
    return response.data.data
  } catch (err) {
    if (err instanceof AxiosError) {
      const body = err.response?.data as { detail?: unknown } | undefined
      throw new Error(formatErrorDetail(body?.detail, 'Your password could not be changed. Please try again.'))
    }
    throw err
  }
}
