export interface LoginRequest {
  identifier: string
  password: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

export interface ChangePasswordResult {
  message: string
  password_changed_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in_hours: number
  role: string
  role_code: string[]
  employee_name: string
}

export interface UserSummary {
  id: string
  employee_id?: string | null
  email: string
  employee_code: string
  employee_name: string
  role: string
  role_codes?: string[]
  account_status?: string
  is_active: boolean
  photo_reference?: string | null
}

export interface CurrentAuthorization {
  role_codes: string[]
  permission_codes: string[]
  employee_code: string | null
}

export interface ApiSuccessEnvelope<T> {
  status: 'success'
  data: T
}

export interface ApiErrorEnvelope {
  status: 'error'
  detail: string
}
