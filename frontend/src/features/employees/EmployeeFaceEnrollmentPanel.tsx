import { useEffect, useState } from 'react'
import { Camera, CheckCircle2 } from 'lucide-react'
import { enrollFace } from '../../lib/enrollmentApi'
import type { Employee } from '../../types/employee'
import type { EnrollmentResult } from '../../types/enrollment'
import { useBlinkWebcamCapture } from '../../hooks/useBlinkWebcamCapture'

interface Props {
  employee: Employee | null
  isActive: boolean
  onPhotoReferenceSaved?: (photoReference: string) => void
}

export default function EmployeeFaceEnrollmentPanel({ employee, isActive, onPhotoReferenceSaved }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [result, setResult] = useState<EnrollmentResult | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const webcam = useBlinkWebcamCapture()
  const stopCamera = webcam.stop

  useEffect(() => {
    setFile(null)
    setPreviewUrl(null)
    setResult(null)
    setError('')
  }, [employee?.id])

  useEffect(() => {
    setError('')
    setResult(null)
  }, [employee?.id, isActive])

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  useEffect(() => {
    stopCamera()
  }, [employee?.id, isActive, stopCamera])

  function selectFile(nextFile: File | null) {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(nextFile)
    setPreviewUrl(nextFile ? URL.createObjectURL(nextFile) : null)
    setResult(null)
    setError('')
  }

  async function capturePhoto() {
    const photo = await webcam.capture()
    if (photo) {
      selectFile(photo)
      webcam.stop()
    }
  }

  async function submitEnrollment() {
    if (!employee || !employee.is_active || employee.record_status !== 'ACTIVE') {
      setError('An active employee profile is required for face enrollment.')
      return
    }
    if (!file) {
      setError('Capture a face photo after blinking first.')
      return
    }

    setError('')
    setIsSubmitting(true)
    try {
      const enrollmentResult = await enrollFace(file, employee.id)
      setFile(null)
      setResult(enrollmentResult)
      if (enrollmentResult.photo_reference) {
        onPhotoReferenceSaved?.(enrollmentResult.photo_reference)
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Face enrollment failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!employee) {
    return (
      <section className="flex items-start gap-3 rounded-xl border border-indigo-100 bg-indigo-50/70 p-5">
        <div className="rounded-lg bg-white p-2 text-indigo-600 shadow-sm"><Camera className="h-5 w-5" /></div>
        <div>
          <h3 className="text-sm font-bold text-slate-900">Face enrollment</h3>
          <p className="mt-1 text-sm text-slate-600">Save the employee record before enrolling a face.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="flex flex-col gap-4">
      {result && !isActive && (
        <p role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          Face sample enrolled. {result.sample_count} sample{result.sample_count === 1 ? '' : 's'} on file.
        </p>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(17rem,0.9fr)]">
        <div className="flex flex-col gap-2">
          <div className={`relative flex aspect-[5/3] w-full items-center justify-center overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 ${isActive ? 'min-h-[16rem] max-h-[75svh]' : 'min-h-52'}`}>
            <video
              ref={webcam.videoRef}
              muted
              autoPlay
              playsInline
              aria-label="Live camera preview"
              className={`absolute inset-0 h-full w-full object-cover ${webcam.isActive ? '' : 'hidden'}`}
            />
            {webcam.isActive ? (
              <>
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/20 via-transparent to-black/40" />
                <div className="pointer-events-none absolute inset-x-[28%] inset-y-[10%] rounded-[45%] border-2 border-white/80 shadow-[0_0_0_999px_rgba(15,23,42,0.16)]" />
                <span className="absolute bottom-3 rounded-full bg-slate-950/65 px-3 py-1 text-[11px] font-medium text-white">
                  Center the face in the frame
                </span>
              </>
            ) : previewUrl ? (
              <img src={previewUrl} alt="Selected employee face preview" className="h-full w-full object-contain" />
            ) : (
              <div className="flex flex-col items-center gap-2 px-5 text-center">
                <div className="rounded-full bg-white/10 p-3 text-slate-300"><Camera className="h-6 w-6" /></div>
                <p className="text-sm font-semibold text-white">No image selected</p>
                <p className="text-xs text-slate-400">Start the camera and blink before capturing the face.</p>
              </div>
            )}
          </div>
          {file && !webcam.isActive && (
            <p className="truncate text-xs text-slate-500" title={file.name}>Selected: {file.name}</p>
          )}
          {webcam.blinkStatus && <p role="status" className="text-sm text-indigo-700">{webcam.blinkStatus}</p>}
        </div>

        <div className="flex flex-col justify-center gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5">
          {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
          {webcam.error && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{webcam.error}</p>}
          {result && isActive && (
            <p role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
              Face sample enrolled. {result.sample_count} sample{result.sample_count === 1 ? '' : 's'} on file.
            </p>
          )}
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-slate-500">Before you capture</p>
            <ul className="mt-2 space-y-1.5 text-sm leading-5 text-slate-600">
              <li>• Use one face, looking toward the camera.</li>
              <li>• Keep the face clear and evenly lit.</li>
              <li>• Blink once when prompted, then reopen both eyes.</li>
              <li>• Avoid sunglasses, masks, and strong backlighting.</li>
            </ul>
          </div>

          {webcam.isActive ? (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={webcam.isCheckingBlink || isSubmitting} onClick={() => void capturePhoto()} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2">
                <Camera className="h-4 w-4" aria-hidden="true" /> {webcam.isCheckingBlink ? 'Waiting for blink...' : 'Blink and capture'}
              </button>
              <button type="button" onClick={webcam.stop} className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-100">
                Cancel camera
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={isSubmitting} onClick={() => { selectFile(null); void webcam.start() }} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50">
                <Camera className="h-4 w-4" aria-hidden="true" /> Use webcam
              </button>
            </div>
          )}

          <button
            type="button"
            disabled={!employee.is_active || employee.record_status !== 'ACTIVE' || !file || isSubmitting || webcam.isActive}
            onClick={() => void submitEnrollment()}
            className="w-full rounded-lg border border-indigo-700 bg-white px-4 py-2.5 text-sm font-bold text-indigo-700 transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
          >
            {isSubmitting ? 'Enrolling face…' : result ? 'Enrolled' : 'Save Face Captured'}
          </button>
          <p className="text-center text-[11px] leading-4 text-slate-500">
            {employee.is_active && employee.record_status === 'ACTIVE'
              ? `Linked directly to employee profile: ${employee.employee_no}`
              : 'An active employee profile is required.'}
          </p>
        </div>
      </div>
    </section>
  )
}
