import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { fetchMyScheduleAssignments } from '../lib/scheduleUploadApi'
import type { MyScheduleAssignment } from '../lib/scheduleUploadApi'
import { formatPeriod, formatTime } from '../lib/scheduleUploadFormat'
import {
  fetchEmergencyScheduleTemplates,
  fetchMyEmergencyScheduleRequests,
  submitEmergencyScheduleRequest,
} from '../lib/emergencyScheduleApi'
import type {
  EmergencyScheduleRequest,
  EmergencyScheduleTemplateOption,
} from '../lib/emergencyScheduleApi'
import { hasPermission } from '../types/role'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function workHours(assignment: MyScheduleAssignment) {
  if (assignment.work_segments.length === 0) return '—'
  return assignment.work_segments
    .map((segment) => `${formatTime(segment.start_time)}–${formatTime(segment.end_time)}${segment.end_day_offset > 0 ? ' (+1 day)' : ''}`)
    .join(', ')
}

function localDateString(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 10)
}

function earliestEmergencyFilingDate() {
  return localDateString(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000))
}

function requestStatusLabel(status: EmergencyScheduleRequest['status']) {
  return {
    PENDING_APPROVAL: 'Pending supervisor approval',
    APPROVED: 'Approved',
    REJECTED: 'Rejected',
  }[status]
}

export default function MySchedule({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [assignments, setAssignments] = useState<MyScheduleAssignment[]>([])
  const [requests, setRequests] = useState<EmergencyScheduleRequest[]>([])
  const [workDate, setWorkDate] = useState(() => localDateString(new Date()))
  const [templates, setTemplates] = useState<EmergencyScheduleTemplateOption[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [requestLoading, setRequestLoading] = useState(true)
  const [templatesLoading, setTemplatesLoading] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let isCurrent = true
    fetchMyScheduleAssignments()
      .then((result) => {
        if (isCurrent) setAssignments(result)
      })
      .catch((cause: unknown) => {
        if (isCurrent) setError(cause instanceof Error ? cause.message : 'Could not load your schedule.')
      })
      .finally(() => {
        if (isCurrent) setLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [])

  useEffect(() => {
    if (!hasPermission('schedule.request_emergency')) return
    let isCurrent = true
    fetchMyEmergencyScheduleRequests()
      .then((result) => {
        if (isCurrent) setRequests(result)
      })
      .catch((cause: unknown) => {
        if (isCurrent) setError(cause instanceof Error ? cause.message : 'Could not load emergency schedule requests.')
      })
      .finally(() => {
        if (isCurrent) setRequestLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [])

  useEffect(() => {
    if (!hasPermission('schedule.request_emergency') || !workDate) {
      return
    }
    let isCurrent = true
    fetchEmergencyScheduleTemplates(workDate)
      .then((result) => {
        if (!isCurrent) return
        setTemplates(result)
        setSelectedTemplateId(result[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (isCurrent) {
          setTemplates([])
          setError(cause instanceof Error ? cause.message : 'Could not load schedule templates.')
        }
      })
      .finally(() => {
        if (isCurrent) setTemplatesLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [workDate])

  async function handleSubmitEmergencyRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedTemplateId) {
      setError('Choose an active schedule template before submitting.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const request = await submitEmergencyScheduleRequest({
        schedule_template_id: selectedTemplateId,
        work_date: workDate,
        reason,
      })
      setRequests((current) => [request, ...current.filter((item) => item.id !== request.id)])
      setReason('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not submit the emergency schedule request.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="my-schedule" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full space-y-4 px-4 py-6 sm:px-6 lg:px-8">
        <header>
          <h1 className="text-xl font-bold text-slate-900">My Schedule</h1>
          <p className="mt-1 text-xs text-slate-600">Your current and upcoming approved work schedules.</p>
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          {loading ? (
            <p role="status" className="px-5 py-6 text-xs text-slate-500">Loading schedule…</p>
          ) : assignments.length === 0 ? (
            <p className="px-5 py-6 text-xs text-slate-500">You have no current or upcoming approved schedule.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-xs">
                <thead className="bg-slate-50 uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Period</th>
                    <th className="px-4 py-2">Schedule</th>
                    <th className="px-4 py-2">Work hours</th>
                    <th className="px-4 py-2">Rest days</th>
                    <th className="px-4 py-2">Type</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {assignments.map((assignment) => (
                    <tr key={assignment.assignment_id}>
                      <td className="whitespace-nowrap px-4 py-2 font-medium text-slate-800">
                        {formatPeriod(assignment.effective_from, assignment.effective_to)}
                      </td>
                      <td className="px-4 py-2">
                        <p className="font-medium text-slate-800">{assignment.schedule_name}</p>
                        <p className="text-[11px] text-slate-500">{assignment.schedule_code} · {assignment.schedule_type}</p>
                      </td>
                      <td className="px-4 py-2">{workHours(assignment)}</td>
                      <td className="px-4 py-2">{assignment.rest_day_pattern_name ?? assignment.rest_day_pattern_code ?? '—'}</td>
                      <td className="px-4 py-2">{assignment.assignment_type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {hasPermission('schedule.request_emergency') && (
          <>
            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-bold text-slate-900">Request an emergency schedule change</h2>
              <p className="mt-1 text-xs text-slate-600">
                Request a one-day replacement schedule. Your regular schedule stays unchanged; the replacement
                affects attendance only after your supervisor approves it. You may file up to 7 days after the
                work date if it is within the current open payroll cutoff. Approved past-date requests recalculate
                attendance from recorded punches. Use the date the shift starts, including overnight schedules.
              </p>
              <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={handleSubmitEmergencyRequest}>
                <label className="grid gap-1 text-xs font-semibold text-slate-700">
                  Work date
                  <input
                    type="date"
                    required
                    min={earliestEmergencyFilingDate()}
                    value={workDate}
                    onChange={(event) => {
                      const nextDate = event.target.value
                      setWorkDate(nextDate)
                      setTemplates([])
                      setSelectedTemplateId('')
                      setTemplatesLoading(Boolean(nextDate))
                      setError('')
                    }}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"
                  />
                </label>
                <label className="grid gap-1 text-xs font-semibold text-slate-700">
                  Replacement schedule
                  <select
                    required
                    value={selectedTemplateId}
                    onChange={(event) => setSelectedTemplateId(event.target.value)}
                    disabled={templatesLoading || templates.length === 0}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal disabled:bg-slate-100"
                  >
                    <option value="">
                      {templatesLoading ? 'Loading schedules…' : 'Select an active schedule'}
                    </option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.schedule_code} · {template.schedule_name} ({template.schedule_type})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold text-slate-700 md:col-span-2">
                  Reason
                  <textarea
                    required
                    maxLength={500}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    rows={3}
                    placeholder="Explain why this emergency schedule change is needed."
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"
                  />
                </label>
                {templates.length === 0 && !templatesLoading && (
                  <p className="text-xs text-amber-700 md:col-span-2">
                    No active schedule templates are available for the employee on this date.
                  </p>
                )}
                <div className="md:col-span-2">
                  <button
                    type="submit"
                    disabled={submitting || templatesLoading || templates.length === 0}
                    className="rounded-lg bg-indigo-700 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {submitting ? 'Submitting…' : 'Submit for supervisor approval'}
                  </button>
                </div>
              </form>
            </section>

            <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <header className="border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-bold text-slate-900">My emergency schedule requests</h2>
              </header>
              {requestLoading ? (
                <p role="status" className="px-5 py-6 text-xs text-slate-500">Loading requests…</p>
              ) : requests.length === 0 ? (
                <p className="px-5 py-6 text-xs text-slate-500">You have no emergency schedule requests.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {requests.map((request) => (
                    <li key={request.id} className="grid gap-1 px-5 py-4 text-xs md:grid-cols-[1fr_auto]">
                      <div>
                        <p className="font-semibold text-slate-800">
                          {request.work_date} · {request.schedule_code} — {request.schedule_name}
                        </p>
                        <p className="mt-1 text-slate-600">{request.reason}</p>
                        {request.review_remarks && (
                          <p className="mt-1 text-slate-500">Supervisor note: {request.review_remarks}</p>
                        )}
                      </div>
                      <span className={`font-semibold ${
                        request.status === 'APPROVED'
                          ? 'text-emerald-700'
                          : request.status === 'REJECTED'
                            ? 'text-rose-700'
                            : 'text-amber-700'
                      }`}>
                        {requestStatusLabel(request.status)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  )
}
