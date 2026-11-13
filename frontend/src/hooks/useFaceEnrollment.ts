import { useEffect, useRef, useState } from 'react'
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
  const generation = useRef(0)

  useEffect(() => () => { generation.current += 1 }, [])
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  function changeEmployeeCode(next: string) {
    generation.current += 1
    setEmployeeCode(next)
    setVerifiedUser(null)
    setFile(null)
    setPreviewUrl(null)
    setResult(null)
    setIsVerifying(false)
    setIsSubmitting(false)
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
    const request = ++generation.current

    try {
      const user = await searchUserByEmployeeCode(code)
      if (request !== generation.current) return
      if (!user.is_active) {
        setVerifiedUser(null)
        setError('This employee account is inactive.')
        return
      }
      setVerifiedUser(user)
    } catch (err) {
      if (request === generation.current) {
        setVerifiedUser(null)
        setError(err instanceof Error ? err.message : 'Employee code could not be verified.')
      }
    } finally {
      if (request === generation.current) setIsVerifying(false)
    }
  }

  function selectFile(nextFile: File | null) {
    setFile(nextFile)
    setResult(null)
    setError(null)
    setPreviewUrl(nextFile ? URL.createObjectURL(nextFile) : null)
  }

  async function submit() {
    if (isSubmitting) return
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
    const request = generation.current

    try {
      const enrollment = await enrollFace(file, verifiedUser.employee_id ?? verifiedUser.id)
      if (request !== generation.current) return
      setFile(null)
      setResult(enrollment)
    } catch (err) {
      if (request === generation.current) setError(err instanceof Error ? err.message : 'Face enrollment failed. Please try again.')
    } finally {
      if (request === generation.current) setIsSubmitting(false)
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
