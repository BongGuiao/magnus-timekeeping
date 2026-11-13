import { useEffect, useEffectEvent, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiClient } from '../lib/apiClient'
import { fetchClockPolicy } from '../lib/attendanceApi'
import type { AttendanceLocation } from '../lib/attendanceApi'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import Stepper from '../components/common/Stepper'
import { useWebcamCapture } from '../hooks/useWebcamCapture'
import { useAttendanceClock, type AttendanceClockTransport } from '../hooks/useAttendanceClock'
import { useLogout } from '../hooks/useLogout'
import type { BreakType, ClockResult, LastAttendance } from '../types/attendance'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
  kioskTransport?: AttendanceClockTransport
}

type PendingConfirmation =
  | { kind: 'attendance'; clockOutConfirmed: boolean; earlyClockOut: boolean; totalWorked?: string }
  | { kind: 'break'; label: string }

const actionLabels: Record<string, string> = {
  clock_in: 'Clocked In',
  clock_out: 'Clocked Out',
  first_break_out_at: 'First Break Started',
  first_break_in_at: 'First Break Ended',
  meal_break_out_at: 'Meal Break Started',
  meal_break_in_at: 'Meal Break Ended',
  second_break_out_at: 'Second Break Started',
  second_break_in_at: 'Second Break Ended',
  ot_break_out_at: 'Overtime Break Started',
  ot_break_in_at: 'Overtime Break Ended',
}

const breakTypesByLabel: Record<string, BreakType> = {
  'START FIRST BREAK': 'first_break_out_at',
  'END FIRST BREAK': 'first_break_in_at',
  'START MEAL BREAK': 'meal_break_out_at',
  'END MEAL BREAK': 'meal_break_in_at',
  'START SECOND BREAK': 'second_break_out_at',
  'END SECOND BREAK': 'second_break_in_at',
  'START OT BREAK': 'ot_break_out_at',
  'END OT BREAK': 'ot_break_in_at',
}

const CAMERA_SETTLE_DELAY_MS = 700
const ERROR_DISMISS_DELAY_MS = 5000
const ATTENDANCE_TIME_ZONE = 'Asia/Manila'

const steps = [
  { label: 'Identify', description: 'Enter employee number' },
  { label: 'Face Match', description: 'Match against enrollment' },
  { label: 'Recorded', description: 'Time in / out saved' },
]

function parseAttendanceTime(value: string) {
  const normalized = value
    .trim()
    .replace(' ', 'T')
    .replace(/\s+([+-]\d{2}:?\d{2})$/, '$1')
    .replace(/([+-]\d{2})(\d{2})$/, '$1:$2')
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(normalized) ? normalized : `${normalized}+08:00`)
}

function formatTime(value: string | null) {
  if (!value) return '—'
  const timestamp = parseAttendanceTime(value)
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        timeZone: ATTENDANCE_TIME_ZONE,
      })
    : '—'
}

function formatDateTime(value: string) {
  const timestamp = parseAttendanceTime(value)
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleString([], { timeZone: ATTENDANCE_TIME_ZONE })
    : value
}

function formatWorkedTime(attendance: LastAttendance, now: number) {
  if (!attendance.clock_in_at) return '0 hours 0 minutes'

  const clockIn = parseAttendanceTime(attendance.clock_in_at)
  if (!Number.isFinite(clockIn)) return 'Unknown'

  const breaks = [
    [attendance.first_break_out_at, attendance.first_break_in_at],
    [attendance.meal_break_out_at, attendance.meal_break_in_at],
    [attendance.second_break_out_at, attendance.second_break_in_at],
    [attendance.ot_break_out_at, attendance.ot_break_in_at],
  ]
  const slots = ['FIRST_BREAK', 'MEAL_BREAK', 'SECOND_BREAK', 'OT_BREAK']
  const breakMilliseconds = breaks.reduce((total, [breakStart, breakEnd], index) => {
    if (!breakStart) return total
    const start = parseAttendanceTime(breakStart)
    const end = breakEnd ? parseAttendanceTime(breakEnd) : now
    const rule = attendance.break_rules?.find((item) => item.break_slot === slots[index])
    const isPaidBreak = rule && (
      ['FIRST_BREAK', 'SECOND_BREAK', 'OT_BREAK'].includes(rule.break_slot)
      || rule.segment_type === 'PAID_BREAK'
    )
    const paidAllowance = isPaidBreak ? rule.break_minutes * 60_000 : 0
    return Number.isFinite(start) && Number.isFinite(end)
      ? total + Math.max(0, end - start - paidAllowance) : total
  }, 0)
  const totalMinutes = Math.max(0, Math.floor((now - clockIn - breakMilliseconds) / 60_000))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours} hour${hours === 1 ? '' : 's'} ${minutes} minute${minutes === 1 ? '' : 's'}`
}

function getCurrentLocation(): Promise<AttendanceLocation> {
  if (!navigator.geolocation) {
    return Promise.reject(new Error('Location services are not available in this browser.'))
  }
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const location = {
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracyMeters: coords.accuracy,
        }
        console.info('[attendance:gps] Browser geolocation reading', {
          latitude: location.latitude,
          longitude: location.longitude,
          accuracyMeters: location.accuracyMeters,
          timestamp: new Date().toISOString(),
          enableHighAccuracy: true,
        })
        resolve(location)
      },
      (error) => {
        const messages: Record<number, string> = {
          1: 'Location permission is required to clock in.',
          2: 'Your current location could not be determined. Check device location settings and try again.',
          3: 'Getting your location timed out. Please try again.',
        }
        reject(new Error(messages[error.code] ?? 'Could not access your current location.'))
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15_000 },
    )
  })
}

export default function Attendance({ employeeName, onNavigate, onLoggedOut, kioskTransport }: Props) {
  const kiosk = Boolean(kioskTransport)
  const { logout } = useLogout({ onLoggedOut })
  const webcam = useWebcamCapture()
  const [employeePhotoUrl, setEmployeePhotoUrl] = useState<string | null>(null)
  const [isAutoCapturePending, setIsAutoCapturePending] = useState(false)
  const [isWaitingForBlink, setIsWaitingForBlink] = useState(false)
  const [blinkStatus, setBlinkStatus] = useState('')
  const [currentTime, setCurrentTime] = useState(() => Date.now())
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null)
  const [attendanceSuccess, setAttendanceSuccess] = useState<ClockResult | null>(null)
  const [locationWarning, setLocationWarning] = useState<string | null>(null)
  const {
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
    clearError: clearAttendanceError,
    reportError,
  } = useAttendanceClock(kioskTransport)

  const dismissErrors = useEffectEvent(() => {
    clearAttendanceError()
    webcam.clearError()
  })

  useEffect(() => {
    if (kiosk) return
    const photoReference = verifiedUser?.photo_reference
    if (!photoReference) {
      setEmployeePhotoUrl(null)
      return
    }

    let isCurrent = true
    let objectUrl: string | null = null
    setEmployeePhotoUrl(null)
    apiClient.get<Blob>(photoReference, { responseType: 'blob' })
      .then(({ data }) => {
        if (!isCurrent) return
        objectUrl = URL.createObjectURL(data)
        setEmployeePhotoUrl(objectUrl)
      })
      .catch(() => {
        if (isCurrent) setEmployeePhotoUrl(null)
      })

    return () => {
      isCurrent = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [kiosk, verifiedUser?.photo_reference])

  async function runAutoCapture(pending: PendingConfirmation) {
    setIsAutoCapturePending(true)
    setLocationWarning(null)
    try {
      let location: AttendanceLocation | undefined
      const policy = kiosk ? { channel: 'kiosk', geofence_required: false } : await fetchClockPolicy()
      if (policy.channel !== 'kiosk') {
        const locationRequired = pending.kind === 'attendance'
          && !pending.clockOutConfirmed && policy.geofence_required
        try {
          location = await getCurrentLocation()
        } catch (locationError) {
          if (locationRequired) throw locationError
          setLocationWarning(
            `Location unavailable for tracing: ${locationError instanceof Error ? locationError.message : 'GPS could not be obtained.'} The punch can still be submitted.`,
          )
        }
      }
      const cameraStarted = await webcam.start()
      if (!cameraStarted) return

      await new Promise((resolve) => window.setTimeout(resolve, CAMERA_SETTLE_DELAY_MS))
      const video = webcam.videoRef.current
      if (!video) throw new Error('The camera is not ready yet. Please try again.')
      setIsWaitingForBlink(true)
      const { waitForEyeBlink } = await import('../lib/faceBlinkDetection')
      await waitForEyeBlink(video, setBlinkStatus)
      setIsWaitingForBlink(false)
      setBlinkStatus('')
      const image = await webcam.capture()
      if (!image) return

      if (pending.kind === 'attendance') {
        const recordedAttendance = await clockWithFace(
          image,
          pending.clockOutConfirmed,
          location,
          kiosk,
        )
        if (recordedAttendance) setAttendanceSuccess(recordedAttendance)
      } else {
        await recordBreak(image, breakTypesByLabel[pending.label], location)
      }
    } catch (captureError) {
      reportError(captureError instanceof Error ? captureError.message : 'Face capture failed. Please try again.')
    } finally {
      setIsWaitingForBlink(false)
      setBlinkStatus('')
      webcam.stop()
      setIsAutoCapturePending(false)
    }
  }

  useEffect(() => {
    if (!error && !webcam.error) return

    const dismissTimer = window.setTimeout(dismissErrors, ERROR_DISMISS_DELAY_MS)
    return () => window.clearTimeout(dismissTimer)
  }, [error, webcam.error])

  useEffect(() => {
    const clockTimer = window.setInterval(() => setCurrentTime(Date.now()), 30_000)
    return () => window.clearInterval(clockTimer)
  }, [])

  function startOver() {
    webcam.stop()
    webcam.clearError()
    setAttendanceSuccess(null)
    setPendingConfirmation(null)
    setLocationWarning(null)
    changeEmployeeCode('')
  }

  const resetKioskEmployee = useEffectEvent(startOver)
  useEffect(() => {
    if (!kiosk || !verifiedUser || isAutoCapturePending || isSubmitting || isBreakSubmitting) return
    const timer = window.setTimeout(resetKioskEmployee, result || breakResult ? 5_000 : 60_000)
    return () => window.clearTimeout(timer)
  }, [kiosk, verifiedUser, result, breakResult, isAutoCapturePending, isSubmitting, isBreakSubmitting])

  function confirmPendingAction() {
    if (!pendingConfirmation) return
    const action = pendingConfirmation
    setPendingConfirmation(null)
    reset()
    webcam.clearError()
    void runAutoCapture(action)
  }

  const completedResult = result ?? breakResult
  const completedAction = result?.action ?? breakResult?.action_recorded
  const currentStep = completedResult ? 2 : verifiedUser ? 1 : 0
  const kioskClockOut = lastAttendance?.next_action === 'clock_out'
  const showBreakActions = kioskClockOut
  const captureButtonLabel = isSubmitting
    ? 'Matching face…'
    : isWaitingForBlink
      ? 'Blink once to continue…'
      : isAutoCapturePending
        ? 'Preparing camera…'
        : showBreakActions
          ? 'Clock Out'
          : 'Clock In'
  const isClockActionDisabled = isSubmitting
    || isAutoCapturePending
    || !kiosk
  const expectedClockOut = lastAttendance?.expected_clock_out_at
    ? parseAttendanceTime(lastAttendance.expected_clock_out_at)
    : Number.NaN
  function requestClockConfirmation(clockOut = showBreakActions) {
    const now = Date.now()
    setPendingConfirmation({
      kind: 'attendance',
      clockOutConfirmed: clockOut,
      earlyClockOut: clockOut && expectedClockOut > now,
      totalWorked: clockOut && lastAttendance ? formatWorkedTime(lastAttendance, now) : undefined,
    })
  }

  const isOvertimeBreakAvailable = showBreakActions && Number.isFinite(expectedClockOut) && expectedClockOut < currentTime
  const breakActionLabels = (() => {
    if (!showBreakActions || !lastAttendance) return []
    const breakRules = lastAttendance.break_rules?.filter((rule) =>
      rule.segment_type === 'PAID_BREAK' || rule.segment_type === 'UNPAID_BREAK')
    if (!breakRules?.length) return []

    if (lastAttendance.first_break_out_at && !lastAttendance.first_break_in_at) return ['END FIRST BREAK']
    if (lastAttendance.meal_break_out_at && !lastAttendance.meal_break_in_at) return ['END MEAL BREAK']
    if (lastAttendance.second_break_out_at && !lastAttendance.second_break_in_at) return ['END SECOND BREAK']
    if (lastAttendance.ot_break_out_at && !lastAttendance.ot_break_in_at) return ['END OT BREAK']

    if (isOvertimeBreakAvailable) {
      const hasOvertimeBreakRule = breakRules.some((rule) => rule.break_slot === 'OT_BREAK')
      return lastAttendance.ot_break_out_at || !hasOvertimeBreakRule ? [] : ['START OT BREAK']
    }
    const fields = {
      FIRST_BREAK: 'first_break_out_at',
      MEAL_BREAK: 'meal_break_out_at',
      SECOND_BREAK: 'second_break_out_at',
      OT_BREAK: 'ot_break_out_at',
    } as const
    const labels = {
      FIRST_BREAK: 'START FIRST BREAK',
      MEAL_BREAK: 'START MEAL BREAK',
      SECOND_BREAK: 'START SECOND BREAK',
      OT_BREAK: 'START OT BREAK',
    }
    const hasMealRule = breakRules.some((rule) => rule.break_slot === 'MEAL_BREAK')
    const hasFirstRule = breakRules.some((rule) => rule.break_slot === 'FIRST_BREAK')

    return breakRules.filter((rule) => {
      if (lastAttendance[fields[rule.break_slot]]) return false
      if (parseAttendanceTime(rule.start_at) > currentTime || currentTime >= parseAttendanceTime(rule.end_at)) {
        return false
      }

      if (rule.break_slot === 'FIRST_BREAK') {
        if (lastAttendance.second_break_out_at) return false
        return !lastAttendance.meal_break_out_at || Boolean(lastAttendance.meal_break_in_at)
      }

      if (rule.break_slot === 'MEAL_BREAK') {
        return !lastAttendance.second_break_out_at
      }

      if (rule.break_slot === 'SECOND_BREAK') {
        if (hasMealRule && !lastAttendance.meal_break_in_at) return false
        if (hasFirstRule && !lastAttendance.first_break_in_at) return false
        return true
      }

      return false
    }).map((rule) => labels[rule.break_slot])
  })()
  if (!kiosk) {
    return (
      <div className="flex min-h-svh flex-col bg-gradient-to-b from-slate-50 to-slate-100">
        <TopNav employeeName={employeeName} activeView="attendance" onNavigate={onNavigate} onSignOut={logout} />
        <main className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6">
          <section className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
            <p className="text-xs font-bold uppercase tracking-[0.15em] text-indigo-600">Attendance</p>
            <h1 className="mt-2 text-2xl font-extrabold tracking-tight text-slate-900">Use an approved kiosk</h1>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">
              Browser punches are available only from an administrator-approved attendance kiosk at its assigned location.
              Mobile attendance is unchanged.
            </p>
            <a
              href="/kiosk"
              className="mt-6 inline-flex rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700"
            >
              Open Attendance Kiosk
            </a>
          </section>
        </main>
      </div>
    )
  }

  return (
    <div className="scrollbar-hidden flex min-h-svh flex-col overflow-y-auto bg-gradient-to-b from-slate-50 to-slate-100">
      {!kiosk && <TopNav employeeName={employeeName} activeView="attendance" onNavigate={onNavigate} onSignOut={logout} />}

      <main className="flex min-h-max w-full flex-none flex-col px-4 py-4 sm:px-6 lg:px-8">
        <header className="mb-3 shrink-0">
          <p className="text-xs font-bold uppercase tracking-[0.15em] text-indigo-600">Time Clock</p>
          <h1 className="mt-0.5 text-2xl font-extrabold tracking-tight text-slate-900">FACIAL RECOGNITION</h1>
          <p className="mt-1 whitespace-nowrap text-sm leading-relaxed text-slate-500 max-[700px]:hidden">
            Confirm your employee number, then look at the camera to match the enrolled face and record attendance.
          </p>
        </header>

        <section className="flex min-h-0 flex-none flex-col overflow-visible rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="shrink-0 border-b border-slate-100 bg-slate-50/60 px-6 py-3">
            <Stepper steps={steps} currentStep={currentStep} />
          </div>

          {currentStep === 0 && (
            <div className="min-h-0 flex-1 p-5">
              <h2 className="text-base font-bold text-slate-900">Who is clocking in?</h2>
              <p className="mt-1 text-sm text-slate-500">
                Enter the employee number to pull up the matching record.
              </p>
              <p className="mt-2 text-xs font-medium text-indigo-700">
                {kiosk
                  ? 'Registered kiosk: verify your face to record attendance at this location.'
                  : 'Clock-in requires location permission and being inside the employee’s assigned geofence.'}
              </p>

              {locationWarning && <p role="status" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{locationWarning}</p>}
              <form
                className="mt-5"
                onSubmit={(e) => {
                  e.preventDefault()
                  void verifyEmployeeCode()
                }}
              >
                <label htmlFor="attendance-employee-code" className="sr-only">
                  Employee Number
                </label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    id="attendance-employee-code"
                    type="text"
                    value={employeeCode}
                    onChange={(e) => changeEmployeeCode(e.target.value.toUpperCase())}
                    placeholder="Employee number, e.g. EMP-00123"
                    autoComplete="off"
                    autoFocus
                    className="flex-1 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium tracking-wide text-slate-900 outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                  />
                  <button
                    type="submit"
                    disabled={isVerifying || !employeeCode.trim()}
                    className="rounded-xl bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300 disabled:shadow-none"
                  >
                    {isVerifying ? 'Verifying…' : 'Continue'}
                  </button>
                </div>
              </form>

              {error && (
                <div className="mt-5 rounded-xl border border-rose-100 bg-rose-50 px-4 py-3">
                  <p className="text-sm font-medium text-rose-700">{error}</p>
                </div>
              )}
            </div>
          )}

          {currentStep === 1 && verifiedUser && (
            <div className="flex min-h-0 flex-1 flex-col p-4">
              <div className="flex flex-col gap-4 rounded-xl border border-slate-100 bg-slate-50/80 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  {employeePhotoUrl
                    ? <img src={employeePhotoUrl} alt={`${verifiedUser.employee_name} employee reference`} className="h-14 w-14 shrink-0 rounded-full border border-slate-200 object-cover" />
                    : <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-bold text-white">
                      {verifiedUser.employee_name.charAt(0).toUpperCase()}
                    </div>}
                  <div className="leading-tight">
                    <p className="text-sm font-bold text-slate-900">{verifiedUser.employee_name}</p>
                    <p className="text-xs font-medium text-slate-500">{verifiedUser.employee_code}</p>
                  </div>
                </div>

                <div className="sm:ml-auto sm:text-right">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Last Attendance</p>
                  {lastAttendance ? (
                    <div className="mt-1 flex flex-wrap items-center gap-2 sm:justify-end">
                      <span className="text-xs font-semibold text-slate-600">
                        {new Date(`${lastAttendance.work_date}T00:00:00`).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                        })}
                      </span>
                      <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                        In {formatTime(lastAttendance.clock_in_at)}
                      </span>
                      <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700">
                        Out {formatTime(lastAttendance.clock_out_at)}
                      </span>
                    </div>
                  ) : (
                    <p className="mt-1 text-xs font-medium text-slate-400">No records yet</p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={startOver}
                  disabled={isSubmitting || isAutoCapturePending || isBreakSubmitting}
                  className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Change employee
                </button>
              </div>

              <div className="mt-4 flex min-h-0 flex-1 flex-col items-center justify-center gap-3 sm:flex-row sm:items-stretch">
                <div className="flex min-h-0 w-full max-w-2xl flex-1 flex-col gap-3">
                  <div className="relative min-h-48 w-full flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-slate-900 lg:min-h-64">
                  <video
                    ref={webcam.videoRef}
                    muted
                    autoPlay
                    playsInline
                    className={`h-full w-full object-cover ${webcam.isActive ? '' : 'hidden'}`}
                  />
                  {webcam.isActive && (
                    <>
                      <div className="pointer-events-none absolute inset-8 rounded-full border-2 border-white/40" />
                      <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-white">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-500" />
                        Live
                      </span>
                    </>
                  )}
                  {!webcam.isActive && (
                    <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-slate-50">
                      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-200 text-lg text-slate-400">
                        ◎
                      </div>
                      <span className="text-xs font-medium text-slate-400">Camera is off</span>
                    </div>
                  )}
                  </div>

                  {isWaitingForBlink && (
                    <p role="status" className="text-center text-sm font-medium text-indigo-700">
                      {blinkStatus}
                    </p>
                  )}

                  <div className="flex w-full shrink-0 flex-wrap justify-center gap-3">
                    {kiosk ? (
                      <>
                        <button
                          type="button"
                          onClick={() => requestClockConfirmation(kioskClockOut)}
                          disabled={isSubmitting || isAutoCapturePending || !webcam.isCameraApiAvailable}
                          className={`flex-1 rounded-xl px-5 py-4 text-lg font-bold text-white disabled:opacity-50 ${
                            kioskClockOut ? 'bg-indigo-600' : 'bg-emerald-600'
                          }`}
                        >
                          {kioskClockOut ? 'Time Out' : 'Time In'}
                        </button>
                        {isAutoCapturePending && (
                          <p role="status" className="w-full text-center text-sm text-indigo-700">
                            {captureButtonLabel}
                          </p>
                        )}
                      </>
                    ) : webcam.isActive ? (
                      <button
                        type="button"
                        onClick={() => requestClockConfirmation()}
                        disabled={isClockActionDisabled}
                        className="flex-1 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300 disabled:shadow-none"
                      >
                        {captureButtonLabel}
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => requestClockConfirmation()}
                        disabled={
                          isClockActionDisabled
                          || !webcam.isCameraApiAvailable
                        }
                        className="w-full rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300 disabled:shadow-none"
                      >
                        {webcam.isCameraApiAvailable
                          ? captureButtonLabel
                          : 'Camera requires HTTPS'}
                      </button>
                    )}
                  </div>
                </div>

                {breakActionLabels.length > 0 && (
                  <aside className="flex w-full shrink-0 flex-col justify-center gap-2 sm:w-36">
                    <p className="text-center text-[10px] font-bold tracking-[0.2em] text-slate-400">BREAK · FACE MATCH REQUIRED</p>
                    {breakActionLabels.map((label) => (
                      <button
                        key={label}
                        type="button"
                        onClick={() => setPendingConfirmation({ kind: 'break', label })}
                        disabled={isBreakSubmitting || isAutoCapturePending || !kiosk}
                        className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm font-semibold text-amber-700 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isBreakSubmitting ? 'RECORDING…' : label}
                      </button>
                    ))}
                  </aside>
                )}
              </div>

              {(webcam.error || error) && (
                <div className="mt-5 rounded-xl border border-rose-100 bg-rose-50 px-4 py-3">
                  <p className="text-sm font-medium text-rose-700">{webcam.error ?? error}</p>
                </div>
              )}
            </div>
          )}

          {currentStep === 2 && completedResult && completedAction && (
            <div className="min-h-0 flex-1 p-5">
              <div className="flex flex-col items-center py-4 text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500 text-2xl font-bold text-white">
                  ✓
                </div>
                <p className="mt-4 text-2xl font-extrabold tracking-tight text-slate-900">
                  {actionLabels[completedAction] ?? completedAction}
                </p>
                <p className="mt-1 text-sm font-semibold text-slate-600">
                  {completedResult.employee_name} · {completedResult.employee_code}
                </p>
                <p className="mt-1 text-xs text-slate-400">{formatDateTime(completedResult.timestamp)}</p>

                <button
                  type="button"
                  onClick={startOver}
                  className="mt-6 w-full max-w-sm rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
                >
                  Clock Another Employee
                </button>
              </div>
            </div>
          )}
        </section>
      </main>

      {pendingConfirmation && createPortal(
        <div
          role="presentation"
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-4 sm:items-center"
          onClick={() => setPendingConfirmation(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="attendance-confirmation-title"
            className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="attendance-confirmation-title" className="text-lg font-bold text-slate-900">
              {pendingConfirmation.kind === 'attendance'
                ? pendingConfirmation.clockOutConfirmed ? 'End shift?' : 'Start shift?'
                : 'Confirm break action'}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              {pendingConfirmation.kind === 'attendance'
                ? pendingConfirmation.clockOutConfirmed
                  ? pendingConfirmation.earlyClockOut
                    ? 'Your scheduled time out is later than the current time. Are you sure you want to Time Out?'
                    : 'Are you sure you want to end your shift for the day?'
                  : 'Are you sure you want to record your clock in?'
                : `Are you sure you want to ${pendingConfirmation.label.toLowerCase()}?`}
            </p>
            {pendingConfirmation.kind === 'attendance' && pendingConfirmation.totalWorked && (
              <div className="mt-4 rounded-lg bg-indigo-50 px-4 py-3">
                <p className="text-xs font-bold uppercase text-indigo-500">Total hours worked</p>
                <p className="mt-1 text-lg font-bold text-indigo-700">{pendingConfirmation.totalWorked}</p>
              </div>
            )}
            <div className="mt-5 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setPendingConfirmation(null)}
                className="rounded-lg border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
              >
                {pendingConfirmation.kind === 'attendance' && pendingConfirmation.earlyClockOut ? 'No' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={confirmPendingAction}
                className="rounded-lg bg-indigo-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700"
              >
                {pendingConfirmation.kind === 'attendance' && pendingConfirmation.earlyClockOut ? 'Yes' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {attendanceSuccess && createPortal(
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="attendance-success-title"
            className="w-full max-w-sm rounded-lg bg-white p-6 text-center shadow-xl"
          >
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500 text-2xl font-bold text-white">
              ✓
            </div>
            <h2 id="attendance-success-title" className="mt-4 text-2xl font-bold text-slate-900">
              {actionLabels[attendanceSuccess.action] ?? attendanceSuccess.action}
            </h2>
            <p className="mt-2 text-sm font-semibold text-slate-600">
              {attendanceSuccess.employee_name} · {attendanceSuccess.employee_code}
            </p>
            <p className="mt-1 text-xs text-slate-400">{formatDateTime(attendanceSuccess.timestamp)}</p>
            {attendanceSuccess.approval_required && (
              <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
                This attendance record is invalid because it includes a punch without approved browser proof. An approver must review it; contact HR if it remains unresolved.
              </p>
            )}
            <button
              type="button"
              onClick={startOver}
              className="mt-6 w-full rounded-lg bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Done
            </button>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
