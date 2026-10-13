import { useEffect, useState, type FormEvent } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  createLeaveApplication,
  fetchLeaveTypes,
  fetchMyLeaveApplications,
  getAuthenticatedEmployeeId,
  leaveUnitsToMinutes,
  minutesToLeaveUnits,
} from '../lib/leaveApi'
import type { LeaveApplication, LeaveType } from '../lib/leaveApi'

interface Props {
  employeeName: string
  previewOnly?: boolean
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function localDateTime(offsetDays: number, hour: number): string {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  date.setHours(hour, 0, 0, 0)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString()
}

function unitLabel(unit: LeaveType['unit_type']): string {
  return unit.toLowerCase()
}

function formatDuration(minutes: number, unit: LeaveType['unit_type']): string {
  const value = minutesToLeaveUnits(minutes, unit)
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(unit)}`
}

function applicationNumber(): string {
  return `LV-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`
}

async function loadLeaveApplicationData(previewOnly: boolean) {
  const [types, myApplications] = await Promise.all([
    fetchLeaveTypes(),
    previewOnly ? Promise.resolve([]) : fetchMyLeaveApplications(),
  ])
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return {
    allTypes: types,
    activeTypes: types.filter((type) =>
      type.is_active
      && type.status === 'ACTIVE'
      && type.effective_from <= today
      && (!type.effective_to || type.effective_to >= today),
    ),
    applications: myApplications,
  }
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

export default function LeaveApplication({ employeeName, previewOnly = false, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [allLeaveTypes, setAllLeaveTypes] = useState<LeaveType[]>([])
  const [applications, setApplications] = useState<LeaveApplication[]>([])
  const [leaveTypeId, setLeaveTypeId] = useState('')
  const [startAt, setStartAt] = useState(() => localDateTime(1, 9))
  const [endAt, setEndAt] = useState(() => localDateTime(1, 18))
  const [duration, setDuration] = useState('1')
  const [reason, setReason] = useState('')
  const [contactInformation, setContactInformation] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    void loadLeaveApplicationData(previewOnly)
      .then(({ allTypes, activeTypes, applications: myApplications }) => {
        setAllLeaveTypes(allTypes)
        setLeaveTypes(activeTypes)
        setApplications(myApplications)
        setLeaveTypeId(activeTypes[0]?.id ?? '')
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Could not load leave application data.'))
      .finally(() => setLoading(false))
  }, [previewOnly])

  const selectedLeaveType = leaveTypes.find((type) => type.id === leaveTypeId)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (!selectedLeaveType) {
      setError('There are no active leave types available for application.')
      return
    }
    const requestedMinutes = leaveUnitsToMinutes(Number(duration), selectedLeaveType.unit_type)
    if (!Number.isFinite(requestedMinutes) || requestedMinutes <= 0) {
      setError('Enter a leave duration greater than zero.')
      return
    }
    if (new Date(endAt) <= new Date(startAt)) {
      setError('The end date and time must be later than the start date and time.')
      return
    }
    const employeeId = getAuthenticatedEmployeeId()
    if (!employeeId) {
      setError('This account is not linked to an employee profile. Contact your administrator to link the account.')
      return
    }

    setSaving(true)
    try {
      const createdApplication = await createLeaveApplication({
        application_no: applicationNumber(),
        employee_id: employeeId,
        leave_type_id: selectedLeaveType.id,
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        duration_type: selectedLeaveType.unit_type,
        requested_minutes: requestedMinutes,
        reason: reason.trim(),
        contact_information: contactInformation.trim() || null,
        status: 'DRAFT',
      })
      setApplications((current) => [createdApplication, ...current])
      setReason('')
      setContactInformation('')
      setSuccess('Leave application saved as a draft.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save your leave application.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 pb-10">
      <TopNav employeeName={employeeName} activeView="leave-application" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-6xl pt-6">
        <div className="mb-6">
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Employee self-service</p>
          <h1 className="mt-1 text-2xl font-extrabold text-slate-900">Apply for Leave</h1>
          <p className="mt-1 text-sm text-slate-500">
            Leave duration follows the unit configured for each leave type. Your application is saved as a draft.
          </p>
        </div>

        {previewOnly && (
          <p role="status" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Employee dashboard preview: switch to an employee-linked account to load applications and submit a request.
          </p>
        )}

        {error && <p role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          {loading ? <p className="text-sm text-slate-500">Loading leave options…</p> : (
            <form onSubmit={(event) => void submit(event)} className="grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-semibold text-slate-700">
                Leave type
                <select required value={leaveTypeId} onChange={(event) => setLeaveTypeId(event.target.value)} className={inputClass}>
                  {leaveTypes.length === 0 && <option value="">No active leave types</option>}
                  {leaveTypes.map((type) => <option key={type.id} value={type.id}>{type.leave_name} ({unitLabel(type.unit_type)})</option>)}
                </select>
              </label>
              <label className="text-sm font-semibold text-slate-700">
                Requested duration ({selectedLeaveType ? unitLabel(selectedLeaveType.unit_type) : 'unit'})
                <input
                  required
                  type="number"
                  min="0.001"
                  step="0.001"
                  value={duration}
                  onChange={(event) => setDuration(event.target.value)}
                  className={inputClass}
                />
                {selectedLeaveType && <span className="mt-1 block text-xs font-normal text-slate-500">Equivalent to {leaveUnitsToMinutes(Number(duration) || 0, selectedLeaveType.unit_type).toLocaleString()} minutes</span>}
              </label>
              <label className="text-sm font-semibold text-slate-700">
                Start
                <input required type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} className={inputClass} />
              </label>
              <label className="text-sm font-semibold text-slate-700">
                End
                <input required type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} className={inputClass} />
              </label>
              <label className="text-sm font-semibold text-slate-700 sm:col-span-2">
                Reason
                <textarea required minLength={1} value={reason} onChange={(event) => setReason(event.target.value)} rows={3} className={inputClass} />
              </label>
              <label className="text-sm font-semibold text-slate-700 sm:col-span-2">
                Contact information during leave (optional)
                <textarea value={contactInformation} onChange={(event) => setContactInformation(event.target.value)} rows={2} className={inputClass} />
              </label>
              <div className="sm:col-span-2">
                <button
                  type="submit"
                  disabled={previewOnly || saving || loading || leaveTypes.length === 0}
                  className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save draft'}
                </button>
              </div>
            </form>
          )}
        </section>

        <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 className="text-lg font-bold text-slate-900">My Leave Applications</h2>
          {applications.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">{loading ? 'Loading applications…' : 'No leave applications yet.'}</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <tr><th className="px-3 py-3">Application</th><th className="px-3 py-3">Leave type</th><th className="px-3 py-3">Dates</th><th className="px-3 py-3">Duration</th><th className="px-3 py-3">Status</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {applications.map((application) => {
                    const type = allLeaveTypes.find((item) => item.id === application.leave_type_id)
                    return (
                      <tr key={application.id}>
                        <td className="px-3 py-3 font-medium text-slate-800">{application.application_no}</td>
                        <td className="px-3 py-3 text-slate-600">{type?.leave_name ?? 'Leave type'}</td>
                        <td className="px-3 py-3 text-slate-600">{formatDateTime(application.start_at)} – {formatDateTime(application.end_at)}</td>
                        <td className="px-3 py-3 text-slate-600">{formatDuration(application.requested_minutes, type?.unit_type ?? 'MINUTES')}</td>
                        <td className="px-3 py-3"><span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">{application.status}</span></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
