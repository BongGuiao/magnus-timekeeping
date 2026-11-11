import { useState } from 'react'
import { clockAttendance, clockBreak, fetchLastAttendance } from '../lib/attendanceApi'
import type { AttendanceLocation } from '../lib/attendanceApi'
import { searchUserByEmployeeCode } from '../lib/authApi'
import type { UserSummary } from '../types/auth'
import type { BreakResult, BreakType, ClockResult, LastAttendance } from '../types/attendance'

export interface AttendanceClockTransport {
  identify: (code: string) => Promise<{ user: UserSummary; last_attendance: LastAttendance | null }>
  clock: (file: File, userId: string, clockOut: boolean) => Promise<ClockResult>
  break: (file: File, userId: string, action: BreakType) => Promise<BreakResult>
}

export function useAttendanceClock(transport?: AttendanceClockTransport) {
  const [employeeCode, setEmployeeCode] = useState('')
  const [verifiedUser, setVerifiedUser] = useState<UserSummary | null>(null)
  const [lastAttendance, setLastAttendance] = useState<LastAttendance | null>(null)
  const [isVerifying, setIsVerifying] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isBreakSubmitting, setIsBreakSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ClockResult | null>(null)
  const [breakResult, setBreakResult] = useState<BreakResult | null>(null)

  function changeEmployeeCode(next: string) {
    setEmployeeCode(next)
    setVerifiedUser(null)
    setLastAttendance(null)
    setError(null)
    setResult(null)
    setBreakResult(null)
  }

  async function verifyEmployeeCode() {
    const code = employeeCode.trim()
    if (!code) {
      setError('Please enter your employee number first.')
      return
    }

    setError(null)
    setResult(null)
    setIsVerifying(true)

    try {
      const kioskEmployee = transport ? await transport.identify(code) : null
      const user = kioskEmployee ? kioskEmployee.user : await searchUserByEmployeeCode(code)
      if (!user.is_active) {
        setVerifiedUser(null)
        setError('This employee account is inactive.')
        return
      }
      if (kioskEmployee) {
        setLastAttendance(kioskEmployee.last_attendance)
      } else {
        try {
          setLastAttendance(await fetchLastAttendance(user.id))
        } catch {
          setLastAttendance(null)
        }
      }
      setVerifiedUser(user)
    } catch (err) {
      setVerifiedUser(null)
      setLastAttendance(null)
      setError(err instanceof Error ? err.message : 'Employee code could not be verified.')
    } finally {
      setIsVerifying(false)
    }
  }

  async function clockWithFace(
    file: File,
    clockOutConfirmed = false,
    location?: AttendanceLocation,
    browserApproved = true,
  ) {
    if (!verifiedUser) {
      setError('Please verify your employee number first.')
      return null
    }

    setError(null)
    setResult(null)
    setBreakResult(null)
    setIsSubmitting(true)

    try {
      const clockResult = transport
        ? await transport.clock(file, verifiedUser.id, clockOutConfirmed)
        : await clockAttendance(
        file,
        verifiedUser.id,
        clockOutConfirmed,
        location,
        browserApproved,
      )
      setResult(clockResult)
      if (!transport) {
        try {
          setLastAttendance(await fetchLastAttendance(verifiedUser.id))
        } catch {
          setLastAttendance(null)
        }
      }
      return clockResult
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record attendance. Please try again.')
      return null
    } finally {
      setIsSubmitting(false)
    }
  }

  async function recordBreak(file: File, breakType: BreakType, location?: AttendanceLocation) {
    if (!verifiedUser) {
      setError('Please verify your employee number first.')
      return false
    }

    setError(null)
    setBreakResult(null)
    setIsBreakSubmitting(true)

    try {
      const recordedBreak = transport
        ? await transport.break(file, verifiedUser.id, breakType)
        : await clockBreak(file, breakType, verifiedUser.id, location)
      setBreakResult(recordedBreak)
      if (!transport) {
        try {
          setLastAttendance(await fetchLastAttendance(verifiedUser.id))
        } catch {
          setLastAttendance(null)
        }
      }
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record break. Please try again.')
      return false
    } finally {
      setIsBreakSubmitting(false)
    }
  }

  function reset() {
    setError(null)
    setResult(null)
    setBreakResult(null)
  }

  function clearError() {
    setError(null)
  }

  function reportError(message: string) {
    setError(message)
  }

  return {
    employeeCode,
    changeEmployeeCode,
    verifyEmployeeCode,
    verifiedUser,
    lastAttendance,
    isVerifying,
    isSubmitting,
    isBreakSubmitting,
    error,
    result,
    breakResult,
    clockWithFace,
    recordBreak,
    reset,
    clearError,
    reportError,
  }
}
