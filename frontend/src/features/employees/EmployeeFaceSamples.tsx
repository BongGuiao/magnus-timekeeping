import { useEffect, useRef, useState } from 'react'
import { apiClient } from '../../lib/apiClient'
import { fetchFaceEnrollment, resetFaceEnrollment } from '../../lib/enrollmentApi'
import type { Employee } from '../../types/employee'
import type { FaceEnrollmentReview } from '../../types/enrollment'

interface Props {
  employee: Employee
  isActive: boolean
  disabled: boolean
  refreshVersion: number
  onReset: (photoReference: string | null) => void
  onResettingChange: (resetting: boolean) => void
}

function SavedFacePhoto({ reference, label }: { reference: string | null; label: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setUrl(null)
    setError('')
    if (reference) {
      apiClient.get<Blob>(reference, { responseType: 'blob' }).then(({ data }) => {
        if (!active) return
        objectUrl = URL.createObjectURL(data)
        setUrl(objectUrl)
      }).catch(() => {
        if (active) setError('Saved photo could not be loaded.')
      })
    }
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [reference])
  if (!reference) return <p className="text-xs text-slate-500">No saved reference photo. This sample cannot be visually reviewed.</p>
  if (error) return <p role="alert" className="text-xs text-rose-700">{error}</p>
  return url
    ? <img src={url} alt={label} className="h-32 w-full rounded-lg bg-slate-100 object-contain" />
    : <p className="text-xs text-slate-500">Loading saved photo...</p>
}

export default function EmployeeFaceSamples({
  employee, isActive, disabled, refreshVersion, onReset, onResettingChange,
}: Props) {
  const [review, setReview] = useState<FaceEnrollmentReview | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [message, setMessage] = useState('')
  const [resetting, setResetting] = useState(false)
  const [showReset, setShowReset] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [reason, setReason] = useState('')
  const [reload, setReload] = useState(0)
  const generation = useRef(0)

  useEffect(() => {
    generation.current += 1
    setReview(null)
    setShowReset(false)
    setConfirmation('')
    setReason('')
    setMessage('')
    setActionError('')
    setResetting(false)
    return () => {
      generation.current += 1
      onResettingChange(false)
    }
  }, [employee.id, onResettingChange])

  useEffect(() => {
    if (!isActive) return
    let active = true
    setLoading(true)
    setLoadError('')
    fetchFaceEnrollment(employee.id).then((value) => {
      if (active) setReview(value)
    }).catch((error: unknown) => {
      if (active) {
        setReview(null)
        setLoadError(error instanceof Error ? error.message : 'Saved face samples could not be loaded.')
      }
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [employee.id, isActive, refreshVersion, reload])

  async function reset() {
    if (!review || review.employee_id !== employee.id || !review.samples.length || disabled || resetting || loading || confirmation !== review.employee_no || !reason.trim()) return
    if (!window.confirm(`Permanently remove all ${review.samples.length} face samples for ${employee.first_name} ${employee.last_name} (${review.employee_no})? Face punches will stop until this employee is re-enrolled. Attendance records will not be deleted.`)) return
    const request = generation.current
    setResetting(true)
    onResettingChange(true)
    setActionError('')
    setMessage('')
    try {
      const result = await resetFaceEnrollment(employee.id, {
        employee_no: confirmation, sample_ids: review.samples.map((sample) => sample.id), reason: reason.trim(),
      })
      if (request !== generation.current) return
      setReview(null)
      setShowReset(false)
      setConfirmation('')
      setReason('')
      setMessage(`No face samples remain. Verify ${review.employee_no} in person, then enroll the correct face.`)
      setActionError(result.cleanup_warning ?? '')
      onReset(result.photo_reference)
    } catch (error) {
      if (request === generation.current) setActionError(error instanceof Error ? error.message : 'Face enrollment could not be reset.')
    } finally {
      if (request === generation.current) {
        setResetting(false)
        onResettingChange(false)
        setReload((value) => value + 1)
      }
    }
  }

  return (
    <section aria-label="Saved face samples" className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-900">Saved face samples - HR Admin review</h3>
        <button type="button" disabled={disabled || resetting || loading} onClick={() => setReload((value) => value + 1)} className="text-sm font-semibold text-indigo-700 disabled:opacity-50">Refresh samples</button>
      </div>
      {loading && <p role="status" className="text-sm text-slate-500">Loading saved face samples...</p>}
      {loadError && <p role="alert" className="text-sm text-rose-700">{loadError}</p>}
      {actionError && <p role="alert" className="text-sm text-rose-700">{actionError}</p>}
      {message && <p role="status" className="text-sm text-emerald-800">{message}</p>}
      {review && !loading && (
        <>
          {review.samples.length === 0 ? (
            <p role="status" className="text-sm text-slate-700">No face samples are enrolled for {review.employee_no}.</p>
          ) : (
            <p className="text-sm text-slate-700">
              {review.enrolled_count} enrolled sample(s); {review.samples.length} saved record(s) for {review.employee_no}.
              {' '}The profile photo is not the complete enrollment history.
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-3">
            {review.samples.map((sample, index) => (
              <article key={sample.id} className="space-y-2 rounded-lg border border-slate-200 p-3">
                <SavedFacePhoto reference={sample.photo_reference} label={`Saved face sample ${index + 1} for ${review.employee_no}`} />
                <p className="text-xs text-slate-600">Sample {index + 1}: {sample.status}{sample.is_profile_photo ? ' (profile photo)' : ''}</p>
                <p className="text-xs text-slate-500">{new Date(sample.enrolled_at ?? sample.created_at).toLocaleString()}</p>
              </article>
            ))}
          </div>
          {review.samples.length > 0 && (
            <>
              <p className="text-xs text-slate-600">Review every available sample against the employee in person. Reset only confirmed incorrect enrollment; this does not approve a borderline match or change the strict threshold.</p>
              <button type="button" disabled={disabled || resetting} onClick={() => setShowReset((value) => !value)} className="text-sm font-semibold text-rose-700 disabled:opacity-50">Remove all face samples</button>
              {showReset && (
                <div className="space-y-3 rounded-lg border border-rose-200 bg-rose-50 p-3">
                  <p className="text-sm text-rose-800">This permanently removes only this employee's face samples and any profile photo linked to them. Face punches will be unavailable until re-enrollment. Existing attendance is preserved.</p>
                  <label className="block text-sm">Type employee number {review.employee_no} to confirm
                    <input aria-label="Confirm face reset employee number" value={confirmation} disabled={resetting} onChange={(event) => setConfirmation(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 p-2" />
                  </label>
                  <label className="block text-sm">Reason for resetting enrollment
                    <textarea aria-label="Face reset reason" value={reason} maxLength={500} disabled={resetting} onChange={(event) => setReason(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 p-2" />
                  </label>
                  <button type="button" disabled={disabled || resetting || confirmation !== review.employee_no || !reason.trim()} onClick={() => void reset()} className="rounded bg-rose-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
                    {resetting ? 'Removing samples...' : 'Confirm removal of all face samples'}
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}
