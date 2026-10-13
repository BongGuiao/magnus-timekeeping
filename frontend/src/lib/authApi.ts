import { AxiosError } from 'axios'
import { apiClient } from './apiClient'
import type { ApiErrorEnvelope, ApiSuccessEnvelope, LoginRequest, TokenResponse, UserSummary } from '../types/auth'

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
