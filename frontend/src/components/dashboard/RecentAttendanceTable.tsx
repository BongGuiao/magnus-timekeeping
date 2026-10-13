import type { AttendanceLogEntry, OvertimeApplicationType } from '../../types/dashboard'

interface Props {
  entries: AttendanceLogEntry[]
  isLoading?: boolean
  error?: string | null
  refreshedAt?: string | null
}

const applicationLabels: Record<OvertimeApplicationType, string> = {
  REGULAR_OVERTIME: 'Regular OT',
  NIGHT_DIFFERENTIAL_OVERTIME: 'Night OT',
  NIGHT_DIFFERENTIAL: 'Night Diff',
}

function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00+08:00`)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString('en-PH', { timeZone: 'Asia/Manila', month: 'short', day: 'numeric', year: 'numeric' })
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' })
}

function getElapsedMinutes(startTime: string | null, endTime: string | null): number | null {
  if (!startTime || !endTime) return null
  const start = new Date(startTime).getTime()
  const end = new Date(endTime).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null
  return Math.floor((end - start) / 60_000)
}

function formatHoursWorked(workedMinutes: number | null | undefined): string {
  if (workedMinutes == null) return '—'
  return `${Math.floor(workedMinutes / 60)}h ${workedMinutes % 60}m`
}

function formatMinutes(value: number): string {
  if (value <= 0) return '—'
  const hours = Math.floor(value / 60)
  const minutes = value % 60
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`
}

function isUnderScheduledHours(entry: AttendanceLogEntry): boolean {
  if (entry.undertimeMinutes !== undefined) return entry.undertimeMinutes > 0
  if (entry.isUndertime !== undefined) return entry.isUndertime
  const workedMinutes = getElapsedMinutes(entry.timeIn, entry.timeOut)
  const expectedTimeIn = entry.expectedTimeIn ?? null
  const expectedTimeOut = entry.expectedTimeOut ?? null
  const scheduledMinutes = expectedTimeIn === null && expectedTimeOut === null
    ? 9 * 60
    : getElapsedMinutes(expectedTimeIn, expectedTimeOut)
  return workedMinutes !== null && scheduledMinutes !== null && workedMinutes < scheduledMinutes
}

export default function RecentAttendanceTable({ entries, isLoading = false, error, refreshedAt }: Props) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-500">Recent Attendance</h2>
        {refreshedAt && <p className="text-xs text-slate-400">
          Updated {new Date(refreshedAt).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' })}
        </p>}
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[1320px] text-left text-sm">
          <thead>
            <tr className="text-xs text-slate-400">
              {['Date', 'Time In', 'Late', 'Logout', 'Under Time', 'Regular OT', 'Night OT', 'Total Night Diff', 'Hours Worked', 'Logout Status', 'OT Approval'].map((heading) =>
                <th key={heading} className="pb-2 font-medium">{heading}</th>,
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading ? (
              <tr><td colSpan={11} className="py-4 text-center text-sm text-slate-500">Loading recent attendance…</td></tr>
            ) : entries.length === 0 ? (
              <tr><td colSpan={11} className="py-4 text-center text-sm text-slate-500">
                {error ? 'Attendance could not be loaded.' : 'No attendance records found.'}
              </td></tr>
            ) : entries.map((entry) => (
              <tr key={`${entry.date}-${entry.timeIn ?? ''}-${entry.timeOut ?? ''}`}>
                <td className="py-2 text-slate-700">{formatDate(entry.date)}</td>
                <td className={`py-2 ${entry.isLate || entry.status === 'late' ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatTime(entry.timeIn)}
                </td>
                <td className={`py-2 ${entry.lateMinutes ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatMinutes(entry.lateMinutes ?? 0)}
                </td>
                <td className="py-2 text-slate-700">{formatTime(entry.timeOut)}</td>
                <td className={`py-2 ${entry.undertimeMinutes ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatMinutes(entry.undertimeMinutes ?? 0)}
                </td>
                <td className="py-2 text-slate-700" title="Potential overtime outside the 10:00 PM–6:00 AM night period">
                  {formatMinutes(entry.overtimeRequestStatus === 'APPROVED' ? entry.approvedRegularOvertimeMinutes ?? 0 : entry.regularOvertimeMinutes ?? 0)}
                  {entry.overtimeRequestStatus === 'APPROVED' ? ' approved'
                    : entry.regularOvertimeHours !== undefined && entry.regularOvertimeMinutes ? ` (${entry.regularOvertimeHours.toFixed(2)}h potential)` : ''}
                </td>
                <td className="py-2 text-slate-700" title="Potential overtime overlapping 10:00 PM–6:00 AM; approval is separate">
                  {formatMinutes(entry.overtimeRequestStatus === 'APPROVED' ? entry.approvedNightDifferentialOvertimeMinutes ?? 0 : entry.nightDifferentialOvertimeMinutes ?? 0)}
                  {entry.overtimeRequestStatus === 'APPROVED' ? ' approved'
                    : entry.nightDifferentialOvertimeHours !== undefined && entry.nightDifferentialOvertimeMinutes ? ` (${entry.nightDifferentialOvertimeHours.toFixed(2)}h potential)` : ''}
                </td>
                <td className="py-2 text-slate-700" title="All hours worked from 10:00 PM to 6:00 AM, including scheduled hours">
                  {formatMinutes(entry.overtimeRequestStatus === 'APPROVED' ? entry.approvedNightDifferentialMinutes ?? 0 : entry.nightDifferentialMinutes ?? 0)}
                  {entry.overtimeRequestStatus === 'APPROVED' ? ' approved'
                    : entry.nightDifferentialHours !== undefined && entry.nightDifferentialMinutes ? ` (${entry.nightDifferentialHours.toFixed(2)}h potential)` : ''}
                </td>
                <td className="py-2 font-bold text-black" title={isUnderScheduledHours(entry) ? 'Below scheduled shift duration' : undefined}>
                  {formatHoursWorked(entry.minutesWorked)}
                </td>
                <td className="py-2">
                  <span className={`rounded-full px-2 py-1 text-xs font-medium ${
                    entry.status === 'no-logout' ? 'bg-amber-50 text-amber-700'
                      : entry.status === 'no-login' ? 'bg-rose-50 text-rose-700'
                        : entry.status === 'on-leave' ? 'bg-slate-100 text-slate-600'
                          : 'bg-emerald-50 text-emerald-700'
                  }`}>
                    {entry.status === 'no-logout' ? 'No Logout' : entry.status === 'no-login' ? 'No Login' : entry.status === 'on-leave' ? 'On Leave' : 'Logout'}
                  </span>
                </td>
                <td className="py-3">
                  {(entry.overtimeApplications ?? []).map((application) => (
                    <p key={application.id} className={`text-xs ${application.status === 'APPROVED' ? 'text-emerald-700' : application.status === 'REJECTED' ? 'text-rose-700' : 'text-amber-700'}`}>
                      {applicationLabels[application.overtimeType]} · {formatMinutes(application.requestedMinutes)} · {application.status}
                      {application.finalPayableMinutes !== null ? ` · payable ${formatMinutes(application.finalPayableMinutes)}` : ''}
                    </p>
                  ))}
                  {!entry.overtimeApplications?.length && <span className="text-xs text-slate-400">No applications</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
