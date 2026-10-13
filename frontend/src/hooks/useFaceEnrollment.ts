import { useState } from 'react'
import { enrollFace } from '../lib/enrollmentApi'
import { searchUserByEmployeeCode } from '../lib/authApi'
import type { UserSummary } from '../types/auth'
import type { EnrollmentResult } from '../types/enrollment'

export function useFaceEnrollment() {
  const [employeeCode, setEmployeeCode] = useState('')
  const [verifiedUser, setVerifiedUser] = useState<UserSummary | null>(null)
  const [isVerifying, setIsVerifying] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EnrollmentResult | null>(null)

  function changeEmployeeCode(next: string) {
    setEmployeeCode(next)
    setVerifiedUser(null)
    setError(null)
  }

  async function verifyEmployeeCode() {
    const code = employeeCode.trim()
    if (!code) {
      setError('Please enter an employee number first.')
      return
    }

    setError(null)
    setIsVerifying(true)

    try {
      const user = await searchUserByEmployeeCode(code)
      if (!user.is_active) {
        setVerifiedUser(null)
        setError('This employee account is inactive.')
        return
      }
      setVerifiedUser(user)
    } catch (err) {
      setVerifiedUser(null)
      setError(err instanceof Error ? err.message : 'Employee code could not be verified.')
    } finally {
      setIsVerifying(false)
    }
  }

  function selectFile(nextFile: File | null) {
    setFile(nextFile)
    setResult(null)
    setError(null)
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return nextFile ? URL.createObjectURL(nextFile) : null
    })
  }

  async function submit() {
    if (!verifiedUser) {
      setError('Please verify the employee number first.')
      return
    }

    if (!file) {
      setError('Please select or capture a photo first.')
      return
    }

    setError(null)
    setIsSubmitting(true)

    try {
      const enrollment = await enrollFace(file, verifiedUser.employee_id ?? verifiedUser.id)
      setResult(enrollment)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Face enrollment failed. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return {
    employeeCode,
    changeEmployeeCode,
    verifyEmployeeCode,
    verifiedUser,
    isVerifying,
    file,
    previewUrl,
    isSubmitting,
    error,
    result,
    selectFile,
    submit,
  }
}
