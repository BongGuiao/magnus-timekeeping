import { useEffect, useState, type FormEvent } from 'react'
import { GitMerge, X } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  fetchAttendanceDetailReport,
  type AttendanceDetailReportFilters,
  type AttendanceDetailReportRecord,
} from '../lib/attendanceReportApi'
import {
  createAttendanceMerge,
  fetchMergeScheduleTemplates,
  type AttendanceMergeScheduleTemplate,
} from '../lib/attendanceMergeApi'
import { getAvailableRoleCodes } from '../types/role'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function localDateValue(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Manila',
  })
}

function formatDate(value: string): string {
  const [year, month, day] = value.split('-')
  return `${month}-${day}-${year}`
}

function AttendanceMergeManagement({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const today = new Date()
  const defaultFrom = localDateValue(new Date(today.getFullYear(), today.getMonth(), 1))
  const defaultTo = localDateValue(today)
  const isHrAdmin = getAvailableRoleCodes().some(
    (roleCode) => roleCode.trim().toUpperCase() === 'HR_ADMIN',
  )
  const [fromDate, setFromDate] = useState(defaultFrom)
  const [toDate, setToDate] = useState(defaultTo)
  const [employeeNo, setEmployeeNo] = useState('')
  const [query, setQuery] = useState<AttendanceDetailReportFilters>({
    from_date: defaultFrom,
    to_date: defaultTo,
    scope: 'organization',
  })
  const [records, setRecords] = useState<AttendanceDetailReportRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [templates, setTemplates] = useState<AttendanceMergeScheduleTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [verifiedClockOut, setVerifiedClockOut] = useState('')
  const [reason, setReason] = useState('')
  const [mergeError, setMergeError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [mergeLoading, setMergeLoading] = useState(false)

  const attendanceGroups = new Map<string, AttendanceDetailReportRecord[]>()
  for (const record of records) {
    if (!record.attendance_id || record.is_merge_result) continue
    const key = `${record.employee_no}:${record.work_date}`
    attendanceGroups.set(key, [...(attendanceGroups.get(key) ?? []), record])
  }
  const selectedRecords = records.filter(
    (record) => record.attendance_id && selectedIds.includes(record.attendance_id),
  )
  const selectedGroupKey = selectedRecords.length
    ? `${selectedRecords[0].employee_no}:${selectedRecords[0].work_date}`
    : null
  const selectedRecordsWithClockIn = selectedRecords.flatMap((record) => (
    record.clock_in_at
      ? [{ record, clockInTimestamp: Date.parse(record.clock_in_at) }]
      : []
  ))
  const latestSelectedClockIn = selectedRecordsWithClockIn.length
    ? Math.max(...selectedRecordsWithClockIn.map(({ clockInTimestamp }) => clockInTimestamp))
    : null
  const requiresVerifiedClockOut = latestSelectedClockIn !== null
    && selectedRecordsWithClockIn.some(
      ({ record, clockInTimestamp }) => clockInTimestamp === latestSelectedClockIn && !record.clock_out_at,
    )

  useEffect(() => {
    let isCurrent = true
    setIsLoading(true)
    setError(null)
    fetchAttendanceDetailReport(query)
      .then((result) => {
        if (isCurrent) {
          setRecords(result)
          setSelectedIds([])
        }
      })
      .catch((loadError: unknown) => {
        if (isCurrent) {
          setRecords([])
          setError(loadError instanceof Error ? loadError.message : 'Could not load attendance records.')
        }
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [query])

  function runSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice(null)
    setSelectedIds([])
    setQuery({
      from_date: fromDate,
      to_date: toDate,
      scope: 'organization',
      employee_no: employeeNo.trim(),
    })
  }

  function toggleSelection(record: AttendanceDetailReportRecord, checked: boolean) {
    if (!record.attendance_id) return
    const attendanceId = record.attendance_id
    const key = `${record.employee_no}:${record.work_date}`
    if (checked) {
      if (selectedGroupKey && selectedGroupKey !== key) return
      setSelectedIds((current) => [...new Set([...current, attendanceId])])
    } else {
      setSelectedIds((current) => current.filter((id) => id !== attendanceId))
    }
  }

  async function openMergeDialog() {
    if (selectedIds.length < 2) return
    setMergeError(null)
    setNotice(null)
    setMergeLoading(true)
    try {
      const options = await fetchMergeScheduleTemplates(selectedIds[0])
      setTemplates(options)
      setSelectedTemplateId(options[0]?.id ?? '')
      setVerifiedClockOut('')
      setIsDialogOpen(true)
    } catch (cause) {
      setMergeError(cause instanceof Error ? cause.message : 'Could not load schedules for this attendance date.')
    } finally {
      setMergeLoading(false)
    }
  }

  async function submitMerge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedIds.length < 2 || !selectedTemplateId || !reason.trim()) return
    setMergeLoading(true)
    setMergeError(null)
    try {
      const result = await createAttendanceMerge({
        source_attendance_ids: selectedIds,
        schedule_template_id: selectedTemplateId,
        reason: reason.trim(),
        verified_clock_out_at: requiresVerifiedClockOut && verifiedClockOut
          ? `${verifiedClockOut}:00+08:00`
          : null,
      })
      setNotice(
        `Canonical attendance created for ${result.work_date}: ${formatTime(result.clock_in_at)}–${formatTime(result.clock_out_at)} using ${result.schedule_code}.`,
      )
      setSelectedIds([])
      setIsDialogOpen(false)
      setVerifiedClockOut('')
      setReason('')
      setQuery((current) => ({ ...current }))
    } catch (cause) {
      setMergeError(cause instanceof Error ? cause.message : 'Could not merge the attendance records.')
    } finally {
      setMergeLoading(false)
    }
  }

  if (!isHrAdmin) {
    return (
      <div className="min-h-screen bg-slate-50">
        <TopNav employeeName={employeeName} activeView="attendance-merge-management" onNavigate={onNavigate} onSignOut={logout} />
        <main className="mx-auto max-w-3xl px-4 py-10">
          <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
            Attendance merging is available to HR Admin only.
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="attendance-merge-management" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">Attendance Merge</h1>
          <p className="mt-1 text-sm text-slate-600">
            Find duplicate attendance records, verify their punches, and create one canonical record. Original records remain unchanged and auditable.
          </p>
        </header>

        <form
          onSubmit={runSearch}
          className="mb-5 grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_auto]"
        >
          <label className="text-sm font-medium text-slate-700">
            From
            <input required type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-sm font-medium text-slate-700">
            To
            <input required type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-sm font-medium text-slate-700">
            Employee number (optional)
            <input type="text" value={employeeNo} onChange={(event) => setEmployeeNo(event.target.value)} placeholder="All employees" className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <button type="submit" disabled={isLoading} className="self-end rounded-lg bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-60">
            {isLoading ? 'Loading…' : 'Find records'}
          </button>
        </form>

        <section className="mb-5 rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Create canonical attendance</h2>
              <p className="mt-1 text-xs text-slate-600">
                Select at least two records for one employee and work date. The result uses the earliest clock-in and latest clock-out.
              </p>
            </div>
            <button type="button" onClick={() => void openMergeDialog()} disabled={selectedIds.length < 2 || mergeLoading} className="inline-flex items-center gap-2 rounded-lg bg-indigo-700 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-50">
              <GitMerge className="h-4 w-4" aria-hidden="true" />
              {mergeLoading ? 'Loading…' : `Merge selected (${selectedIds.length})`}
            </button>
          </div>
          {mergeError && !isDialogOpen && <p role="alert" className="mt-3 text-sm text-rose-700">{mergeError}</p>}
          {notice && <p role="status" className="mt-3 text-sm text-emerald-800">{notice}</p>}
        </section>

        {error && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
        {!error && !isLoading && records.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-600">
            No attendance records found for the selected dates and employee.
          </div>
        )}
        {records.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-4 py-3">Select</th>
                  <th className="px-4 py-3">Work date</th>
                  <th className="px-4 py-3">Employee</th>
                  <th className="px-4 py-3">Schedule</th>
                  <th className="px-4 py-3">Clock in</th>
                  <th className="px-4 py-3">Clock out</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {records.map((record) => {
                  const key = `${record.employee_no}:${record.work_date}`
                  const hasDuplicates = (attendanceGroups.get(key)?.length ?? 0) > 1
                  const selectable = Boolean(
                    record.attendance_id
                    && !record.is_merge_result
                    && record.attendance_mode === 'PUNCH_REQUIRED'
                    && record.record_status === 'VALID'
                    && hasDuplicates,
                  )
                  return (
                    <tr key={record.attendance_id ?? `${key}-credited`} className="align-top hover:bg-slate-50">
                      <td className="px-4 py-3">
                        {selectable ? (
                          <input
                            type="checkbox"
                            aria-label={`Select ${record.employee_no} attendance on ${record.work_date}`}
                            checked={Boolean(record.attendance_id && selectedIds.includes(record.attendance_id))}
                            disabled={Boolean(selectedGroupKey && selectedGroupKey !== key)}
                            onChange={(event) => toggleSelection(record, event.target.checked)}
                          />
                        ) : record.is_merge_result ? 'Canonical' : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">{formatDate(record.work_date)}</td>
                      <td className="px-4 py-3">{record.employee_no} · {record.employee_name}</td>
                      <td className="px-4 py-3">{record.schedule_code ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3">{formatTime(record.clock_in_at)}</td>
                      <td className="whitespace-nowrap px-4 py-3">{formatTime(record.clock_out_at)}</td>
                      <td className="px-4 py-3">{record.is_merge_result ? 'Merge result' : record.record_status}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          {records.length} record{records.length === 1 ? '' : 's'} · Search up to 31 days at a time.
        </p>

        {isDialogOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
            <form role="dialog" aria-modal="true" aria-labelledby="attendance-merge-title" onSubmit={submitMerge} className="w-full max-w-xl space-y-4 rounded-xl bg-white p-6 shadow-xl">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 id="attendance-merge-title" className="text-lg font-bold text-slate-900">Create canonical attendance</h2>
                  <p className="mt-1 text-sm text-slate-600">The selected original records remain unchanged and are retained in the audit history.</p>
                </div>
                <button type="button" aria-label="Close merge dialog" onClick={() => setIsDialogOpen(false)} className="rounded p-1 text-slate-500 hover:bg-slate-100">
                  <X className="h-5 w-5" aria-hidden="true" />
                </button>
              </div>
              <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
                Verify the source punches. The result uses the earliest clock-in and latest clock-out.
              </p>
              {requiresVerifiedClockOut && (
                <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3">
                  <p className="text-sm text-amber-900">
                    The latest selected sequence has no clock-out. Enter the employee’s verified actual clock-out; the original punch records will remain unchanged and this value will be included in the merge audit.
                  </p>
                  <label className="block text-sm font-medium text-slate-700">
                    HR-verified clock-out (Philippine time)
                    <input
                      required
                      type="datetime-local"
                      step={60}
                      value={verifiedClockOut}
                      onChange={(event) => setVerifiedClockOut(event.target.value)}
                      disabled={mergeLoading}
                      className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                    />
                  </label>
                </div>
              )}
              <label className="block text-sm font-medium text-slate-700">
                Schedule for this work date
                <select required value={selectedTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)} disabled={templates.length === 0 || mergeLoading} className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2">
                  <option value="">Select a valid schedule</option>
                  {templates.map((template) => <option key={template.id} value={template.id}>{template.schedule_code} — {template.schedule_name}</option>)}
                </select>
              </label>
              {templates.length === 0 && <p role="alert" className="text-sm text-rose-700">No active schedule template is valid for this employee and date.</p>}
              <label className="block text-sm font-medium text-slate-700">
                HR reason / verification
                <textarea required maxLength={1000} rows={3} value={reason} onChange={(event) => setReason(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="Explain why these records are being merged and how the punches were verified." />
              </label>
              {mergeError && <p role="alert" className="text-sm text-rose-700">{mergeError}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setIsDialogOpen(false)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700">Cancel</button>
                <button type="submit" disabled={mergeLoading || !selectedTemplateId || !reason.trim() || templates.length === 0 || (requiresVerifiedClockOut && !verifiedClockOut)} className="rounded-lg bg-indigo-700 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-50">
                  {mergeLoading ? 'Creating…' : 'Create canonical record'}
                </button>
              </div>
            </form>
          </div>
        )}
      </main>
    </div>
  )
}

export default AttendanceMergeManagement
