import { useState } from 'react'
import type { FormEvent } from 'react'
import { fetchCurrentAuthorization, loginRequest } from '../lib/authApi'
import type { TokenResponse } from '../types/auth'

interface UseLoginOptions {
  onSuccess?: (result: TokenResponse) => void
}

export function useLogin(options: UseLoginOptions = {}) {
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      const result = await loginRequest({ identifier, password })
      // Persist so the app can restore the session on refresh
      localStorage.setItem('access_token', result.access_token)
      localStorage.setItem('role', result.role)
      localStorage.setItem('role_codes', JSON.stringify(result.role_code))
      localStorage.removeItem('dashboard_role')
      localStorage.removeItem('dashboard_role_code')
      localStorage.setItem('employee_name', result.employee_name)
      const authorization = await fetchCurrentAuthorization()
      localStorage.setItem('role_codes', JSON.stringify(authorization.role_codes))
      localStorage.setItem('permission_codes', JSON.stringify(authorization.permission_codes))
      options.onSuccess?.(result)
    } catch (err) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('role')
      localStorage.removeItem('role_codes')
      localStorage.removeItem('permission_codes')
      setError(err instanceof Error ? err.message : 'Login failed. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return {
    identifier,
    setIdentifier,
    password,
    setPassword,
    isSubmitting,
    error,
    submit,
  }
}
