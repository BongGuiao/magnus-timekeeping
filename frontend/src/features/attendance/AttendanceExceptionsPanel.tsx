import { useState } from 'react'
import {
  fetchAttendanceExceptions,
  fetchAttendanceExceptionSchedule,
  resolveAttendanceException,
  type AttendanceCorrection,
  type AttendanceExceptionSchedule,
} from '../../lib/attendanceCorrectionApi'

const formatTime = new Intl.DateTimeFormat('en-PH', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Manila',
})
const display = (value: string | null) => value ? formatTime.format(new Date(value)) : 'Missing'
const buttonClass = 'rounded-md border border-indigo-200 px-3 py-1.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50'

export default function AttendanceExceptionsPanel() {
  const [requests, setRequests] = useState<AttendanceCorrection[] | null>(null)
  const [review, setReview] = useState<{ request: AttendanceCorrection; schedule: AttendanceExceptionSchedule } | null>(null)
  const [notes, setNotes] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await action()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not complete attendance exception review.')
    } finally {
      setBusy(false)
    }
  }

  function clearReview() {
    setReview(null)
    setNotes('')
    setConfirmed(false)
  }

  return (
    <section aria-labelledby="hr-attendance-exceptions-title" className="mt-4 space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <h2 id="hr-attendance-exceptions-title" className="text-lg font-bold text-slate-900">Resolve Attendance Exceptions</h2>
      <p className="text-sm text-slate-600">Review pending missing-punch requests whose attendance records lack a saved schedule policy. Confirm the schedule and actual working times with the supervisor. All times shown are Philippine time.</p>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {message && <p role="status" className="text-sm text-emerald-700">{message}</p>}
      {busy && <p role="status" className="text-sm text-slate-600">Working…</p>}
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void run(async () => {
        clearReview()
        setRequests(await fetchAttendanceExceptions())
      })}>{requests === null ? 'Load pending exceptions' : 'Refresh exceptions'}</button>
      {requests?.length === 0 && <p className="text-sm text-slate-600">No pending attendance corrections are missing a saved schedule policy.</p>}
      {requests?.map((request) => (
        <article key={request.id} className="space-y-2 rounded-lg border border-slate-200 p-4 text-sm">
          <h3 className="font-bold text-slate-900">{request.employee_code} - {request.employee_name}: {request.work_date}</h3>
          <p>Original: {display(request.original_clock_in_at)} to {display(request.original_clock_out_at)}</p>
          <p>Requested: {display(request.requested_clock_in_at)} to {display(request.requested_clock_out_at)}</p>
          <p>Reason: {request.reason}</p>
          {request.supporting_reference && <p>Reference: {request.supporting_reference}</p>}
          {review?.request.id === request.id ? (
            <div className="space-y-2 rounded-md bg-slate-50 p-3">
              <p className="font-semibold">{review.schedule.schedule_code}: {display(review.schedule.expected_clock_in_at)} to {display(review.schedule.expected_clock_out_at)}</p>
              <p>Grace: {review.schedule.schedule_context.grace_minutes} min. Overtime eligible: {review.schedule.schedule_context.ot_eligible ? 'Yes' : 'No'}.
                {' '}Minimum overtime: {review.schedule.schedule_context.minimum_ot_minutes} min. Pre-shift overtime: {review.schedule.schedule_context.pre_shift_ot_allowed ? 'Yes' : 'No'}.</p>
              <p>Break rules: {review.schedule.schedule_context.break_rules.length === 0 ? 'None' : review.schedule.schedule_context.break_rules
                .map((rule) => `${rule.break_slot.replaceAll('_', ' ')}: ${rule.break_minutes} min${rule.auto_deduct ? ' (auto-deduct)' : ''}`).join('; ')}</p>
              <label className="block font-semibold">HR review notes
                <textarea className="mt-1 block w-full rounded-md border border-slate-300 p-2" value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={2000} disabled={busy} />
              </label>
              <label className="flex items-start gap-2">
                <input type="checkbox" className="mt-1" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={busy} />
                I verified this was the schedule in force and the requested punch reflects actual work.
              </label>
              <button type="button" className={buttonClass} disabled={busy || !confirmed || !notes.trim()}
                onClick={() => void run(async () => {
                  await resolveAttendanceException(review.request, review.schedule, notes)
                  setRequests((current) => current?.filter((item) => item.id !== request.id) ?? null)
                  clearReview()
                  setMessage('Exception resolved. Recalculate and review cutoff attendance before finalizing.')
                })}>Confirm schedule & approve missing punch</button>
            </div>
          ) : (
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void run(async () => {
              clearReview()
              setReview({ request, schedule: await fetchAttendanceExceptionSchedule(request.id) })
            })}>Review schedule</button>
          )}
        </article>
      ))}
    </section>
  )
}
