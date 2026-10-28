import { useEffect, useState } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  fetchPendingEmergencyScheduleRequests,
  reviewEmergencyScheduleRequest,
} from '../lib/emergencyScheduleApi'
import type { EmergencyScheduleRequest, EmergencyScheduleDecision } from '../lib/emergencyScheduleApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function EmergencyScheduleApprovals({
  employeeName,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [requests, setRequests] = useState<EmergencyScheduleRequest[] | null>(null)
  const [remarks, setRemarks] = useState<Record<string, string>>({})
  const [workingRequestId, setWorkingRequestId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let isCurrent = true
    fetchPendingEmergencyScheduleRequests()
      .then((result) => {
        if (isCurrent) setRequests(result)
      })
      .catch((cause: unknown) => {
        if (!isCurrent) return
        setRequests([])
        setError(cause instanceof Error ? cause.message : 'Could not load emergency schedule requests.')
      })
    return () => {
      isCurrent = false
    }
  }, [])

  async function review(request: EmergencyScheduleRequest, decision: EmergencyScheduleDecision) {
    const reviewNote = remarks[request.id] ?? ''
    if (decision === 'REJECTED' && !reviewNote.trim()) {
      setError('Enter a reason before rejecting this request.')
      return
    }
    setWorkingRequestId(request.id)
    setError('')
    setNotice('')
    try {
      await reviewEmergencyScheduleRequest(request.id, decision, reviewNote)
      setRequests((current) => (current ?? []).filter((item) => item.id !== request.id))
      setNotice(decision === 'APPROVED'
        ? 'Emergency schedule approved. If the work date has passed, attendance was recalculated from recorded punches; otherwise, the replacement will be used when attendance is recorded.'
        : 'Emergency schedule request rejected.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not review the emergency schedule request.')
    } finally {
      setWorkingRequestId('')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView="emergency-schedule-approvals"
        onNavigate={onNavigate}
        onSignOut={logout}
      />
      <main className="w-full space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <header>
          <h1 className="text-xl font-bold text-slate-900">Emergency Schedule Approvals</h1>
          <p className="mt-1 text-xs text-slate-600">
            Review one-day schedule replacement requests from employees currently assigned to you.
            Approval does not change their regular schedule.
          </p>
        </header>

        {error && (
          <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {notice}
          </p>
        )}

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          {requests === null ? (
            <p role="status" className="px-5 py-6 text-xs text-slate-500">Loading requests…</p>
          ) : requests.length === 0 ? (
            <p className="px-5 py-6 text-xs text-slate-500">There are no pending emergency schedule requests for your team.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {requests.map((request) => (
                <li key={request.id} className="space-y-3 px-5 py-4">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {request.employee_code} · {request.employee_name}
                    </p>
                    <p className="mt-1 text-xs font-medium text-slate-700">
                      {request.work_date} · {request.schedule_code} — {request.schedule_name}
                    </p>
                    <p className="mt-1 text-xs text-slate-600">{request.reason}</p>
                  </div>
                  <label className="grid gap-1 text-xs font-semibold text-slate-700">
                    Review note
                    <textarea
                      value={remarks[request.id] ?? ''}
                      onChange={(event) => setRemarks((current) => ({
                        ...current,
                        [request.id]: event.target.value,
                      }))}
                      maxLength={500}
                      rows={2}
                      placeholder="Optional for approval; required when rejecting."
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={workingRequestId !== ''}
                      onClick={() => void review(request, 'APPROVED')}
                      className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
                    >
                      {workingRequestId === request.id ? 'Saving…' : 'Approve'}
                    </button>
                    <button
                      type="button"
                      disabled={workingRequestId !== ''}
                      onClick={() => void review(request, 'REJECTED')}
                      className="rounded-lg border border-rose-300 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  )
}
