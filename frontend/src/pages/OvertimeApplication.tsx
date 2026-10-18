import { useEffect, useState, type FormEvent } from 'react'
import { Clock3, LoaderCircle, Send } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  fetchMyOvertimeApplications, fetchOvertimeAttendanceOptions, submitOvertimeApplication,
  updateOvertimeApplication,
  type OvertimePayrollCutoff,
  type OvertimeApplication as Application,
} from '../lib/attendanceApi'
import type { AttendanceLogEntry, OvertimeApplicationType } from '../types/dashboard'
import { defaultOvertimePeriod, overtimePeriodError, overtimePeriodMinutes, overtimeTimestamp, philippineDateTime, type OvertimePeriod } from '../lib/overtimePeriod'

interface Props {
  employeeName: string
  previewOnly?: boolean
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const labels: Record<OvertimeApplicationType, string> = {
  REGULAR_OVERTIME: 'Regular overtime',
  NIGHT_DIFFERENTIAL_OVERTIME: 'Night differential overtime',
  NIGHT_DIFFERENTIAL: 'Night differential',
}
const types: OvertimeApplicationType[] = ['REGULAR_OVERTIME', 'NIGHT_DIFFERENTIAL_OVERTIME']
const inputClass = 'mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50'

function potential(entry: AttendanceLogEntry, type: OvertimeApplicationType): number {
  switch (type) {
    case 'REGULAR_OVERTIME': return entry.regularOvertimeMinutes ?? 0
    case 'NIGHT_DIFFERENTIAL_OVERTIME': return entry.nightDifferentialOvertimeMinutes ?? 0
    case 'NIGHT_DIFFERENTIAL': return entry.nightDifferentialMinutes ?? 0
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Could not load or submit overtime applications.'
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('en-PH', { timeZone: 'Asia/Manila' })
}

export default function OvertimeApplication({ employeeName, previewOnly = false, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [entries, setEntries] = useState<AttendanceLogEntry[]>([])
  const [cutoff, setCutoff] = useState<OvertimePayrollCutoff | null>(null)
  const [applications, setApplications] = useState<Application[]>([])
  const [attendanceId, setAttendanceId] = useState('')
  const [editingApplicationId, setEditingApplicationId] = useState<string | null>(null)
  const [type, setType] = useState<OvertimeApplicationType>('REGULAR_OVERTIME')
  const [period, setPeriod] = useState<OvertimePeriod>({ requested_start_at: '', requested_end_at: '' })
  const [reason, setReason] = useState('')
  const [work, setWork] = useState('')
  const [loading, setLoading] = useState(!previewOnly)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (previewOnly) return
    let current = true
    Promise.all([fetchOvertimeAttendanceOptions(), fetchMyOvertimeApplications()])
      .then(([snapshot, records]) => {
        if (!current) return
        setEntries(snapshot.entries)
        setCutoff(snapshot.cutoff)
        setApplications(records)
        setLoaded(true)
      })
      .catch((cause: unknown) => { if (current) setError(errorText(cause)) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [previewOnly])

  function availableTypes(entry: AttendanceLogEntry, excludeApplicationId?: string): OvertimeApplicationType[] {
    return types.filter((item) => potential(entry, item) > 0 && !applications.some((application) =>
      application.attendance_record_id === entry.attendanceId && application.overtime_type === item
      && application.id !== excludeApplicationId
      && ['PENDING', 'APPROVED'].includes(application.status),
    ))
  }
  const eligible = entries.filter((entry) =>
    entry.attendanceId && entry.timeOut && entry.status !== 'no-logout' && entry.status !== 'no-login'
    && (
      availableTypes(entry).length > 0
      || applications.some((application) =>
        application.attendance_record_id === entry.attendanceId
        && ['PENDING', 'REJECTED'].includes(application.status)
        && !application.payroll_posted,
      )
    ),
  )
  const selected = eligible.find((entry) => entry.attendanceId === attendanceId)
  const available = selected ? availableTypes(selected, editingApplicationId ?? undefined) : []
  const maximum = selected ? potential(selected, type) : 0
  const duration = overtimePeriodMinutes(period)

  function selectAttendance(id: string) {
    setEditingApplicationId(null)
    const entry = eligible.find((item) => item.attendanceId === id)
    const nextType = entry ? availableTypes(entry)[0] : undefined
    setAttendanceId(id)
    setType(nextType ?? 'REGULAR_OVERTIME')
    if (entry && nextType) {
      const nextPeriod = defaultOvertimePeriod(entry, nextType)
      setPeriod(nextPeriod)
    } else {
      setPeriod({ requested_start_at: '', requested_end_at: '' })
    }
    setSuccess('')
  }

  function editApplication(application: Application) {
    setAttendanceId(application.attendance_record_id)
    setEditingApplicationId(application.id)
    setType(application.overtime_type)
    setPeriod({
      requested_start_at: philippineDateTime(application.requested_start_at),
      requested_end_at: philippineDateTime(application.requested_end_at),
    })
    setReason(application.reason)
    setWork(application.work_accomplished ?? '')
    setError('')
    setSuccess('')
    document.getElementById('overtime-application-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function cancelEdit() {
    setEditingApplicationId(null)
    setAttendanceId('')
    setPeriod({ requested_start_at: '', requested_end_at: '' })
    setReason('')
    setWork('')
    setError('')
    setSuccess('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving || previewOnly || !loaded) return
    setError('')
    setSuccess('')
    const requested = duration
    if (!selected || !available.includes(type) || !Number.isInteger(requested) || requested <= 0 || requested > maximum || !reason.trim()) {
      setError('Select eligible attendance, choose a period within the calculated minute limit, and provide a reason.')
      return
    }
    const periodError = overtimePeriodError(selected, period, requested, maximum)
    if (periodError) {
      setError(periodError)
      return
    }
    setSaving(true)
    try {
      const payload = {
        overtime_type: type, requested_minutes: requested, reason: reason.trim(), work_accomplished: work.trim() || null,
        requested_start_at: overtimeTimestamp(period.requested_start_at),
        requested_end_at: overtimeTimestamp(period.requested_end_at),
      }
      const application = editingApplicationId
        ? await updateOvertimeApplication(editingApplicationId, payload)
        : await submitOvertimeApplication(attendanceId, payload)
      setApplications((current) => editingApplicationId
        ? current.map((item) => item.id === application.id ? application : item)
        : [application, ...current])
      setAttendanceId('')
      setEditingApplicationId(null)
      setPeriod({ requested_start_at: '', requested_end_at: '' })
      setReason('')
      setWork('')
      setSuccess('Overtime application submitted for supervisor approval.')
    } catch (cause) {
      setError(errorText(cause))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-svh bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="overtime-application" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-6xl space-y-5 py-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Employee self-service</p>
            <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Overtime Applications</h1>
            <p className="mt-2 text-sm text-slate-500">Request calculated overtime from completed attendance within your current payroll cutoff. All times are shown in Philippine time.</p>
          </div>
          <button type="button" onClick={() => onNavigate?.('dashboard')} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700">Back to dashboard</button>
        </div>
        {previewOnly && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">Employee preview only. Use an employee-linked account to view and submit applications.</p>}
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{success}</p>}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="flex items-center gap-2 text-base font-bold text-slate-900"><Clock3 className="h-5 w-5 text-indigo-600" aria-hidden="true" />Apply for overtime</h2>
          <p className="mt-2 text-xs leading-5 text-slate-500">Dates, time intervals, and maximum minutes are validated from attendance. Pending or approved types cannot be requested again.</p>
          {cutoff && <p className="mt-3 rounded-lg bg-indigo-50 p-3 text-sm text-indigo-800">Current payroll cutoff: <strong>{cutoff.cutoff_code}</strong> | {cutoff.period_start} to {cutoff.period_end} (inclusive)</p>}
          {loading && <p role="status" className="mt-4 text-sm text-slate-500">Loading eligible attendance...</p>}
          {loaded && eligible.length === 0 && <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">No eligible overtime in your current payroll cutoff. Complete your punches first, or check whether the calculated types already have applications.</p>}
          <form id="overtime-application-form" onSubmit={(event) => void submit(event)} className="mt-5">
            <fieldset disabled={previewOnly || !loaded || loading || saving} className="grid gap-4 sm:grid-cols-2">
              <legend className="sr-only">Overtime application details</legend>
              <label className="text-xs font-semibold text-slate-700">Completed attendance
                <select required value={attendanceId} onChange={(event) => selectAttendance(event.target.value)} className={inputClass}>
                  <option value="">Select an attendance date</option>
                  {eligible.map((entry) => <option key={entry.attendanceId} value={entry.attendanceId}>{entry.date}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-slate-700">Application type
                <select required value={available.includes(type) ? type : ''} onChange={(event) => {
                  const next = types.find((item) => item === event.target.value)
                  if (next && selected) {
                    const nextPeriod = defaultOvertimePeriod(selected, next)
                    setType(next)
                    setPeriod(nextPeriod)
                  }
                }} className={inputClass}>
                  <option value="">Select a type</option>
                  {types.map((item) => <option key={item} value={item} disabled={!available.includes(item)}>
                    {labels[item]}{!selected ? ' - select attendance first' : potential(selected, item) <= 0 ? ' - no calculated minutes' : !available.includes(item) ? ' - already pending/approved' : ''}
                  </option>)}
                </select>
                <p className="mt-1 text-xs font-normal leading-5 text-slate-500">Regular overtime: outside scheduled hours, excluding night hours. Night differential overtime: overtime during 10 PM–6 AM. Night-differential hours within the shift are calculated and approved automatically; no separate application is needed.</p>
              </label>
              {selected && <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:col-span-2">
                <p className="font-semibold text-slate-800">Effective attendance punches</p>
                <p className="mt-1">Clock-in: {selected.timeIn ? formatTime(selected.timeIn) : '--'} | Clock-out: {selected.timeOut ? formatTime(selected.timeOut) : '--'}</p>
                <p className="mt-1">Requested times must stay within these punches. Corrected punches take precedence. Overnight requests include both dates.</p>
              </div>}
              <label className="text-xs font-semibold text-slate-700">Requested start at (Philippine time)
                <input required type="datetime-local" step={1} min={philippineDateTime(selected?.timeIn, true) || undefined} max={philippineDateTime(selected?.timeOut) || undefined} value={period.requested_start_at} onChange={(event) => setPeriod((current) => ({ ...current, requested_start_at: event.target.value }))} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700">Requested end at (Philippine time)
                <input required type="datetime-local" step={1} min={period.requested_start_at || undefined} max={philippineDateTime(selected?.timeOut) || undefined} value={period.requested_end_at} onChange={(event) => setPeriod((current) => ({ ...current, requested_end_at: event.target.value }))} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700">Requested minutes
                <input readOnly type="number" value={duration} className={inputClass} />
                <p className="mt-1 text-xs font-normal text-slate-500">Automatically calculated as requested end minus requested start, in whole minutes. The period must stay within effective attendance punches.</p>
                {duration > maximum && <p role="alert" className="mt-1 text-xs font-normal text-rose-700">Shorten the requested period: {duration} minutes exceeds the calculated maximum of {maximum} minutes.</p>}
              </label>
              <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-3">
                <p className="text-xs text-indigo-700">Calculated maximum</p>
                <p className="mt-1 text-lg font-bold text-indigo-900">{maximum} <span className="text-xs font-medium">minutes</span></p>
              </div>
              <label className="text-xs font-semibold text-slate-700 sm:col-span-2">Reason
                <textarea required maxLength={5000} value={reason} onChange={(event) => setReason(event.target.value)} rows={3} className={inputClass} />
              </label>
              <label className="text-xs font-semibold text-slate-700 sm:col-span-2">Work accomplished (optional)
                <textarea maxLength={5000} value={work} onChange={(event) => setWork(event.target.value)} rows={2} className={inputClass} />
              </label>
              <div className="flex justify-end gap-2 sm:col-span-2">
                {editingApplicationId && <button type="button" onClick={cancelEdit} className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700">Cancel edit</button>}
                <button type="submit" disabled={!selected || duration <= 0 || duration > maximum} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                  {saving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
                  {saving
                    ? (editingApplicationId ? 'Saving...' : 'Submitting...')
                    : editingApplicationId
                      ? (applications.find((application) => application.id === editingApplicationId)?.status === 'REJECTED'
                        ? 'Save changes and resubmit'
                        : 'Save changes')
                      : 'Submit for approval'}
                </button>
              </div>
            </fieldset>
          </form>
        </section>
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="text-base font-bold text-slate-900">My Overtime Applications</h2>
          {!loading && loaded && applications.length === 0 && <p className="mt-4 text-sm text-slate-500">No overtime applications yet.</p>}
          {applications.length > 0 && <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[800px] text-left text-xs">
              <thead className="border-b border-slate-200 text-slate-500"><tr>{['Application', 'Date / interval', 'Type', 'Requested', 'Approved', 'Payable', 'Status', ''].map((heading) => <th key={heading} className="px-3 py-3">{heading}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100">{applications.map((application) => <tr key={application.id}>
                <td className="px-3 py-3 font-semibold text-slate-800">{application.application_no}</td>
                <td className="px-3 py-3 text-slate-600"><p>{application.attendance_date}</p><p className="mt-1">{formatTime(application.requested_start_at)} - {formatTime(application.requested_end_at)}</p></td>
                <td className="px-3 py-3">{labels[application.overtime_type]}</td>
                <td className="px-3 py-3">{application.requested_minutes} min</td>
                <td className="px-3 py-3">{application.supervisor_approved_minutes === null ? '--' : `${application.supervisor_approved_minutes} min`}</td>
                <td className="px-3 py-3">{application.final_payable_minutes === null ? '--' : `${application.final_payable_minutes} min`}</td>
                <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 font-semibold ${application.status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700' : application.status === 'REJECTED' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-700'}`}>{application.status}</span></td>
                <td className="px-3 py-3">{['PENDING', 'REJECTED'].includes(application.status) && !application.payroll_posted && entries.some((entry) => entry.attendanceId === application.attendance_record_id) && <button type="button" onClick={() => editApplication(application)} className="rounded-md border border-indigo-200 px-2.5 py-1.5 font-semibold text-indigo-700 hover:bg-indigo-50">Edit</button>}</td>
              </tr>)}</tbody>
            </table>
          </div>}
        </section>
      </main>
    </div>
  )
}
