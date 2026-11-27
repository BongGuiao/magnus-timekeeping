import { useEffect, useState, type FormEvent } from 'react'
import TopNav, { type NavView } from '../components/dashboard/TopNav'
import AttendanceDeadlines from '../components/common/AttendanceDeadlines'
import { useLogout } from '../hooks/useLogout'
import {
  fetchMyOvertimeApplications,
  fetchRestDayAttendanceOptions,
  submitOvertimeApplication,
  type OvertimeApplication,
  type RestDayAttendanceOption,
} from '../lib/attendanceApi'

interface Props {
  employeeName: string
  previewOnly?: boolean
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function minutesText(minutes: number): string {
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function timeText(value: string): string {
  return new Date(value).toLocaleString('en-PH', { timeZone: 'Asia/Manila' })
}

export default function RestDayApplication({ employeeName, previewOnly = false, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [records, setRecords] = useState<RestDayAttendanceOption[]>([])
  const [applications, setApplications] = useState<OvertimeApplication[]>([])
  const [attendanceId, setAttendanceId] = useState('')
  const [reason, setReason] = useState('')
  const [work, setWork] = useState('')
  const [loading, setLoading] = useState(!previewOnly)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (previewOnly) return
    let active = true
    Promise.all([fetchRestDayAttendanceOptions(), fetchMyOvertimeApplications()])
      .then(([options, requests]) => {
        if (active) {
          setRecords(options)
          setApplications(requests)
        }
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load rest-day work.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [previewOnly])

  const eligible = records.filter((record) => !applications.some((application) =>
    (application.attendance_record_id === record.attendance_id
      || (application.overtime_type === 'REST_DAY_WORK' && application.attendance_date === record.date))
    && ['PENDING', 'APPROVED'].includes(application.status),
  ))
  const selected = eligible.find((record) => record.attendance_id === attendanceId)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected || !reason.trim() || saving || previewOnly) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const application = await submitOvertimeApplication(selected.attendance_id, {
        overtime_type: 'REST_DAY_WORK',
        requested_minutes: selected.rest_day_work_minutes,
        reason: reason.trim(),
        work_accomplished: work.trim() || null,
      })
      setApplications((current) => [application, ...current])
      setAttendanceId('')
      setReason('')
      setWork('')
      setNotice(`${application.application_no} was submitted to your assigned approver.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not submit rest-day work.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="rest-day-application" onNavigate={onNavigate} onSignOut={logout} />
      <main className="space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <h1 className="text-2xl font-extrabold text-slate-900">Rest-Day Work</h1>
        <p className="text-sm text-slate-600">File after clocking out. The complete punched interval is requested without break deductions. Approved minutes start at clock-in: the first 8 hours are rest-day work and the remainder is overtime.</p>
        {previewOnly ? <p>Employee preview only.</p> : <AttendanceDeadlines />}
        {error && <p role="alert" className="rounded-lg bg-rose-50 p-4 text-rose-700">{error}</p>}
        {notice && <p role="status" className="rounded-lg bg-emerald-50 p-4 text-emerald-700">{notice}</p>}
        <form onSubmit={(event) => void submit(event)} className="space-y-4 rounded-xl bg-white p-6 shadow-sm">
          <label className="block text-sm font-semibold">Completed rest-day attendance
            <select required disabled={previewOnly || loading || saving} value={attendanceId} onChange={(event) => setAttendanceId(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 p-2">
              <option value="">{loading ? 'Loading...' : 'Select attendance'}</option>
              {eligible.map((record) => <option key={record.attendance_id} value={record.attendance_id}>{record.date} — {minutesText(record.rest_day_work_minutes)}</option>)}
            </select>
          </label>
          {!loading && !eligible.length && <p className="text-sm text-slate-500">No eligible rest-day attendance in an open payroll cutoff.</p>}
          {selected && <p className="text-sm text-slate-600">{timeText(selected.time_in)} to {timeText(selected.time_out)} · Rest-day work: {minutesText(Math.min(480, selected.rest_day_work_minutes))} · Excess: {minutesText(Math.max(0, selected.rest_day_work_minutes - 480))}</p>}
          <label className="block text-sm font-semibold">Reason
            <textarea required maxLength={5000} disabled={previewOnly || saving} value={reason} onChange={(event) => setReason(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 p-2" />
          </label>
          <label className="block text-sm font-semibold">Work accomplished (optional)
            <textarea maxLength={5000} disabled={previewOnly || saving} value={work} onChange={(event) => setWork(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 p-2" />
          </label>
          <button type="submit" disabled={!selected || !reason.trim() || saving || previewOnly} className="rounded bg-indigo-600 px-4 py-2 font-semibold text-white disabled:opacity-50">{saving ? 'Submitting...' : 'Submit for approval'}</button>
        </form>
        <section className="rounded-xl bg-white p-6 shadow-sm">
          <h2 className="font-bold">My rest-day applications</h2>
          {applications.filter((item) => item.overtime_type === 'REST_DAY_WORK').map((item) =>
            <div key={item.id} className="mt-3 text-sm"><p>{item.attendance_date} · {item.application_no} · {item.status} · Requested {minutesText(item.requested_minutes)}{item.status === 'APPROVED' && ` · Approved ${minutesText(item.final_payable_minutes ?? 0)}`}</p>{item.rejection_reason && <p className="mt-1 whitespace-pre-line text-rose-700">Rejection reason: {item.rejection_reason}</p>}</div>,
          )}
        </section>
      </main>
    </div>
  )
}
