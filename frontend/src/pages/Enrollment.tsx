import { useEffect } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import Stepper from '../components/common/Stepper'
import { useFaceEnrollment } from '../hooks/useFaceEnrollment'
import { useBlinkWebcamCapture } from '../hooks/useBlinkWebcamCapture'
import { useLogout } from '../hooks/useLogout'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const steps = [
  { label: 'Identify', description: 'Enter employee number' },
  { label: 'Capture', description: 'Blink and capture a photo' },
  { label: 'Enrolled', description: 'Face sample saved' },
]

export default function Enrollment({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const {
    employeeCode,
    changeEmployeeCode,
    verifyEmployeeCode,
    verifiedUser,
    isVerifying,
    previewUrl,
    isSubmitting,
    error,
    result,
    selectFile,
    submit,
  } = useFaceEnrollment()
  const webcam = useBlinkWebcamCapture()
  const stopCamera = webcam.stop

  useEffect(() => {
    stopCamera()
  }, [verifiedUser?.id, stopCamera])

  async function handleCapture() {
    const file = await webcam.capture()
    if (file) {
      selectFile(file)
      webcam.stop()
    }
  }

  function startOver() {
    webcam.stop()
    selectFile(null)
    changeEmployeeCode('')
  }

  const currentStep = result ? 2 : verifiedUser ? 1 : 0

  return (
    <div className="scrollbar-hidden flex h-svh flex-col overflow-y-auto bg-gradient-to-b from-slate-50 to-slate-100 md:overflow-hidden">
      <TopNav employeeName={employeeName} activeView="enrollment" onNavigate={onNavigate} onSignOut={logout} />

      <main className="mx-auto flex min-h-max w-[95%] max-w-3xl flex-none flex-col py-4 md:min-h-0 md:flex-1">
        <header className="mb-3 shrink-0">
          <p className="text-xs font-bold uppercase tracking-[0.15em] text-indigo-600">Biometrics</p>
          <h1 className="mt-0.5 text-2xl font-extrabold tracking-tight text-slate-900">Face ID Enrollment</h1>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-500 [@media(max-height:700px)]:hidden">
            Register an employee's face so it can be matched during clock-in and clock-out.             Blink before each capture. Capture several samples in
            different lighting for the best accuracy.
          </p>
        </header>

        <section className="flex min-h-0 flex-1 flex-col overflow-visible rounded-2xl border border-slate-200 bg-white shadow-sm md:overflow-hidden">
          <div className="shrink-0 border-b border-slate-100 bg-slate-50/60 px-6 py-3">
            <Stepper steps={steps} currentStep={currentStep} />
          </div>

          {currentStep === 0 && (
            <div className="min-h-0 flex-1 p-5">
              <h2 className="text-base font-bold text-slate-900">Who are you enrolling?</h2>
              <p className="mt-1 text-sm text-slate-500">
                Enter the employee number to pull up the matching record.
              </p>

              <form
                className="mt-5"
                onSubmit={(e) => {
                  e.preventDefault()
                  void verifyEmployeeCode()
                }}
              >
                <label htmlFor="employee-code" className="sr-only">
                  Employee Number
                </label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    id="employee-code"
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
              <div className="flex items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/80 p-3">
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-bold text-white">
                    {verifiedUser.employee_name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 leading-tight">
                    <p className="truncate text-sm font-bold text-slate-900">{verifiedUser.employee_name}</p>
                    <p className="truncate text-xs font-medium text-slate-500">
                      {verifiedUser.employee_code} · {verifiedUser.email}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={startOver}
                  disabled={isSubmitting || webcam.isCheckingBlink}
                  className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Change employee
                </button>
              </div>

              <p className="mt-3 shrink-0 text-sm text-slate-500 [@media(max-height:700px)]:hidden">
                Look at the live camera in even lighting. Blink once when prompted, then reopen both eyes.
              </p>

              <div className="mt-3 flex min-h-0 flex-1 flex-col items-center gap-2">
                <div className="relative min-h-28 w-full max-w-sm flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-slate-900">
                  <video
                    ref={webcam.videoRef}
                    muted
                    autoPlay
                    playsInline
                    className={`h-full w-full object-cover ${webcam.isActive ? '' : 'hidden'}`}
                  />
                  {webcam.isActive && (
                    <div className="pointer-events-none absolute inset-8 rounded-full border-2 border-white/40" />
                  )}
                  {!webcam.isActive && (
                    <div className="flex h-full w-full items-center justify-center bg-slate-50">
                      {previewUrl ? (
                        <img
                          src={previewUrl}
                          alt="Selected face preview"
                          className="aspect-square h-[70%] max-h-40 rounded-full object-cover ring-4 ring-white"
                        />
                      ) : (
                        <div className="flex aspect-square h-[70%] max-h-40 flex-col items-center justify-center gap-2 rounded-full border-2 border-dashed border-slate-200 bg-white">
                          <span className="text-lg text-slate-300">◎</span>
                          <span className="px-6 text-center text-xs font-medium text-slate-400">No photo selected</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {webcam.blinkStatus && <p role="status" className="text-sm text-indigo-700">{webcam.blinkStatus}</p>}

                <div className="flex w-full max-w-sm shrink-0 flex-wrap justify-center gap-2">
                  {webcam.isActive ? (
                    <>
                      <button
                        type="button"
                        onClick={handleCapture}
                        disabled={webcam.isCheckingBlink || isSubmitting}
                        className="flex-1 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
                      >
                        {webcam.isCheckingBlink ? 'Waiting for blink...' : 'Blink and Capture'}
                      </button>
                      <button
                        type="button"
                        onClick={webcam.stop}
                        className="rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        disabled={isSubmitting}
                        onClick={() => { selectFile(null); void webcam.start() }}
                        className="flex-1 rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                      >
                        Use Webcam
                      </button>
                    </>
                  )}
                </div>

                <button
                  type="button"
                  onClick={submit}
                  disabled={isSubmitting || webcam.isActive || !previewUrl || webcam.isCheckingBlink}
                  className="w-full max-w-sm shrink-0 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300 disabled:shadow-none"
                >
                  {isSubmitting ? 'Enrolling…' : 'Submit Enrollment'}
                </button>
              </div>

              {(webcam.error || error) && (
                <div className="mt-5 rounded-xl border border-rose-100 bg-rose-50 px-4 py-3">
                  <p className="text-sm font-medium text-rose-700">{webcam.error ?? error}</p>
                </div>
              )}
            </div>
          )}

          {currentStep === 2 && result && (
            <div className="min-h-0 flex-1 p-5">
              <div className="flex flex-col items-center py-4 text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500 text-2xl font-bold text-white">
                  ✓
                </div>
                <p className="mt-4 text-2xl font-extrabold tracking-tight text-slate-900">Employee Enrolled</p>
                <p className="mt-1 text-sm font-semibold text-slate-600">
                  {result.sample_count} face sample{result.sample_count === 1 ? '' : 's'} on file
                  {verifiedUser ? ` for ${verifiedUser.employee_name}` : ''}
                </p>
                <p className="mt-1 text-xs text-slate-400">{new Date(result.enrolled_at).toLocaleString()}</p>

                <div className="mt-6 flex w-full max-w-sm flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => selectFile(null)}
                    className="flex-1 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700"
                  >
                    Add Another Image
                  </button>
                  <button
                    type="button"
                    onClick={startOver}
                    className="flex-1 rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
                  >
                    Enroll Someone Else
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
