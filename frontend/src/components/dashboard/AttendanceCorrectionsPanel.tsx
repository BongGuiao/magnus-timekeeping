import { useEffect, useState, type FormEvent } from 'react'
import AttendanceDeadlines from '../common/AttendanceDeadlines'
import {
  decideAttendanceCorrection, fetchAttendanceCorrections, fetchCorrectionDay, submitAttendanceCorrection,
  type AttendanceCorrection, type CorrectionDay,
} from '../../lib/attendanceCorrectionApi'

function philippineInput(value: string | null): string {
  if (!value) return ''
  return new Date(new Date(value).getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 16)
}

function formatPunch(value: string | null): string {
  return value ? new Date(value).toLocaleString('en-PH', { timeZone: 'Asia/Manila' }) : 'Missing'
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm'

export default function AttendanceCorrectionsPanel({ scope, onPendingCountChange }: {
  scope: 'own' | 'team'
  onPendingCountChange?: (count: number | null) => void
}) {
  const [requests, setRequests] = useState<AttendanceCorrection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [saving, setSaving] = useState<string | null>(null)
  const [workDate, setWorkDate] = useState('')
  const [day, setDay] = useState<CorrectionDay | null>(null)
  const [clockIn, setClockIn] = useState('')
  const [clockOut, setClockOut] = useState('')
  const [reason, setReason] = useState('')
  const [reference, setReference] = useState('')
  const [notes, setNotes] = useState<Record<string, string>>({})

  useEffect(() => {
    let current = true
    fetchAttendanceCorrections(scope).then((items) => {
      if (current) { setRequests(items); setLoading(false); onPendingCountChange?.(items.length) }
    }).catch((cause: unknown) => {
      if (current) { setError(cause instanceof Error ? cause.message : 'Could not load correction requests.'); setLoading(false); onPendingCountChange?.(null) }
    })
    return () => { current = false }
  }, [scope, onPendingCountChange])

  async function loadDay() {
    setSaving('load'); setError(''); setSuccess(''); setDay(null)
    try {
      const result = await fetchCorrectionDay(workDate)
      setDay(result); setClockIn(philippineInput(result.clock_in_at)); setClockOut(philippineInput(result.clock_out_at))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load attendance.')
    } finally { setSaving(null) }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!day) { setError('Load the attendance date before filing a correction.'); return }
    setSaving('submit'); setError(''); setSuccess('')
    try {
      const result = await submitAttendanceCorrection({
        work_date: day.work_date,
        requested_clock_in_at: day.clock_in_at ?? `${clockIn}:00+08:00`,
        requested_clock_out_at: day.clock_out_at ?? `${clockOut}:00+08:00`,
        reason: reason.trim(), supporting_reference: reference.trim() || null,
      })
      setRequests((current) => [result, ...current]); setDay(null); setReason(''); setReference('')
      setSuccess('Correction submitted to your assigned approver. Original punches are unchanged.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not submit correction.')
    } finally { setSaving(null) }
  }

  async function decide(request: AttendanceCorrection, decision: 'APPROVED' | 'REJECTED') {
    const remarks = notes[request.id]?.trim()
    if (!remarks) { setError('Provide review notes before approving or rejecting.'); return }
    setSaving(request.id); setError(''); setSuccess('')
    try {
      await decideAttendanceCorrection(request, decision, remarks)
      const remaining = requests.filter((item) => item.id !== request.id)
      setRequests(remaining)
      onPendingCountChange?.(remaining.length)
      setSuccess(decision === 'APPROVED'
        ? 'Correction approved and attendance recalculated. HR must recalculate cutoff attendance before finalization.'
        : 'Correction rejected; attendance punches are unchanged.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save decision.')
    } finally { setSaving(null) }
  }

  const complete = Boolean(day?.clock_in_at && day?.clock_out_at)
  const noPunches = Boolean(day && !day.clock_in_at && !day.clock_out_at)
  return (
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-bold text-slate-900">
        {scope === 'team' ? 'Attendance Correction Approvals' : 'Missing-Punch Corrections'}
      </h2>
      <p className="mt-1 mb-4 text-sm text-slate-500">
        {scope === 'team'
          ? 'Verify the actual working times and reason before deciding. Approval fills missing punches only; overtime requires its own approval.'
          : 'At least one clock-in or clock-out must already exist on the work date. File only the missing punch after the shift ends; existing punches cannot be overwritten.'}
      </p>
      <AttendanceDeadlines scope={scope} />
      {!loading && !error && scope === 'team' && <p className="mb-3 text-sm text-slate-500">{requests.length} pending requests shown (up to 200). Refresh after reviewing to load remaining requests.</p>}
      {error && <p role="alert" className="mb-4 text-sm text-rose-700">{error}</p>}
      {success && <p role="status" className="mb-4 text-sm text-emerald-700">{success}</p>}
      <button type="button" disabled={Boolean(saving) || loading} className="mb-4 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700 shadow-sm transition hover:bg-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        onClick={async () => {
          setSaving('refresh'); setError('')
          try {
            const items = await fetchAttendanceCorrections(scope)
            setRequests(items)
            onPendingCountChange?.(items.length)
          }
          catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not refresh corrections.'); onPendingCountChange?.(null) }
          finally { setSaving(null) }
        }}>Refresh requests</button>
      {scope === 'own' && (
        <div className="mb-6 space-y-3">
          <label className="block text-sm font-semibold">Work date (Philippine time)
            <input type="date" className={inputClass} value={workDate} disabled={Boolean(saving)}
              onChange={(event) => { setWorkDate(event.target.value); setDay(null); setError(''); setSuccess('') }} />
          </label>
          <button type="button" disabled={!workDate || Boolean(saving)} onClick={() => void loadDay()}
            className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700 shadow-sm transition hover:bg-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">Load attendance</button>
          {day && (
            <>
              <p className="text-sm text-slate-600">
                Scheduled: {formatPunch(day.expected_clock_in_at)} to {formatPunch(day.expected_clock_out_at)}.
                Recorded: {formatPunch(day.clock_in_at)} to {formatPunch(day.clock_out_at)}.
              </p>
              {noPunches ? <p role="alert" className="text-sm text-rose-700">At least one existing clock-in or clock-out is required for this work date. Contact HR.</p>
                : complete ? <p role="status" className="text-sm">Both punches exist. No missing-punch correction is needed.</p> : (
                <form onSubmit={(event) => void submit(event)} className="grid gap-3 sm:grid-cols-2">
                  <label className="text-sm font-semibold">Actual clock-in (Philippine time)
                    <input type="datetime-local" required value={clockIn} readOnly={Boolean(day.clock_in_at)}
                      disabled={Boolean(saving)} className={inputClass} onChange={(event) => setClockIn(event.target.value)} />
                  </label>
                  <label className="text-sm font-semibold">Actual clock-out (Philippine time)
                    <input type="datetime-local" required value={clockOut} readOnly={Boolean(day.clock_out_at)}
                      disabled={Boolean(saving)} className={inputClass} onChange={(event) => setClockOut(event.target.value)} />
                  </label>
                  <label className="text-sm font-semibold sm:col-span-2">Reason for missing punch
                    <textarea required maxLength={2000} value={reason} disabled={Boolean(saving)}
                      className={inputClass} onChange={(event) => setReason(event.target.value)} />
                  </label>
                  <label className="text-sm font-semibold sm:col-span-2">Supporting reference (optional)
                    <input maxLength={500} value={reference} disabled={Boolean(saving)} className={inputClass}
                      placeholder="Ticket, job order or other evidence reference"
                      onChange={(event) => setReference(event.target.value)} />
                  </label>
                  <button disabled={Boolean(saving)} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-2">
                    {saving === 'submit' ? 'Submitting...' : 'Submit correction'}
                  </button>
                </form>
              )}
            </>
          )}
        </div>
      )}
      {loading ? <p role="status">Loading correction requests...</p> : error && requests.length === 0 ? null : requests.length === 0
        ? <p className="text-sm text-slate-500">{scope === 'team' ? 'No pending corrections assigned to you.' : 'No correction requests filed.'}</p>
        : <ul className="space-y-4">
          {requests.map((request) => (
            <li key={request.id} className="rounded-lg border border-slate-200 p-4 text-sm">
              <p className="font-bold">{scope === 'team' ? `${request.employee_code} - ${request.employee_name}: ` : ''}{request.work_date} - {request.status}</p>
              <p>Original: {formatPunch(request.original_clock_in_at)} to {formatPunch(request.original_clock_out_at)}</p>
              <p>Requested: {formatPunch(request.requested_clock_in_at)} to {formatPunch(request.requested_clock_out_at)}</p>
              <p className="whitespace-pre-wrap">Reason: {request.reason}</p>
              {request.supporting_reference && <p>Reference: {request.supporting_reference}</p>}
              {request.review_notes && <p>Review notes: {request.review_notes}</p>}
              {scope === 'team' && (
                <div className="mt-3">
                  <label className="block font-semibold">Review notes (required)
                    <textarea className={inputClass} maxLength={2000} value={notes[request.id] ?? ''}
                      disabled={Boolean(saving)} onChange={(event) => setNotes((current) => ({ ...current, [request.id]: event.target.value }))} />
                  </label>
                  <div className="mt-2 flex gap-2">
                    <button type="button" disabled={Boolean(saving)} onClick={() => void decide(request, 'APPROVED')}
                      className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">Approve</button>
                    <button type="button" disabled={Boolean(saving)} onClick={() => void decide(request, 'REJECTED')}
                      className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 shadow-sm transition hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">Reject</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>}
    </section>
  )
}
