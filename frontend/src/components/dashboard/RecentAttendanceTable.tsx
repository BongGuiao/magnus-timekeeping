import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
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

function getNonOvertimeNightDifferentialMinutes(entry: AttendanceLogEntry): number {
  const isApproved = entry.overtimeRequestStatus === 'APPROVED'
  const totalNightDifferential = isApproved
    ? entry.approvedNightDifferentialMinutes ?? 0
    : entry.nightDifferentialMinutes ?? 0
  const overtimeNightDifferential = isApproved
    ? entry.approvedNightDifferentialOvertimeMinutes ?? 0
    : entry.nightDifferentialOvertimeMinutes ?? 0
  return Math.max(0, totalNightDifferential - overtimeNightDifferential)
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
  const [isExpanded, setIsExpanded] = useState(false)

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          aria-expanded={isExpanded}
          aria-controls="recent-attendance-content"
          onClick={() => setIsExpanded((expanded) => !expanded)}
          className="flex items-center gap-2 text-left text-base font-semibold text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          <ChevronDown className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
          <span>Recent Attendance</span>
        </button>
        {refreshedAt && <p className="text-xs text-slate-400">
          Updated {new Date(refreshedAt).toLocaleTimeString('en-PH', { timeZone: 'Asia/Manila', hour: '2-digit', minute: '2-digit' })}
        </p>}
      </div>
      {isExpanded && <div id="recent-attendance-content">
      {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-100">
        <table className="w-full min-w-[1600px] border-separate border-spacing-0 text-left text-xs leading-5">
          <thead>
            <tr className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              {['Date', 'Time In', 'Late', 'Logout', 'Under Time', 'Excess Break', 'Regular OT', 'Non-OT ND', 'Night OT', 'Total Night Diff', 'Hours Worked', 'Logout Status', 'OT Approval'].map((heading) =>
                <th key={heading} className="whitespace-nowrap border-b border-slate-200 px-3 py-2.5 font-semibold">{heading}</th>,
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading ? (
            <tr><td colSpan={13} className="px-3 py-4 text-center text-xs text-slate-500">Loading recent attendance…</td></tr>
            ) : entries.length === 0 ? (
            <tr><td colSpan={13} className="px-3 py-4 text-center text-xs text-slate-500">
                {error ? 'Attendance could not be loaded.' : 'No attendance records found.'}
              </td></tr>
            ) : entries.map((entry) => (
              <tr key={`${entry.date}-${entry.timeIn ?? ''}-${entry.timeOut ?? ''}`}>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-slate-700">{formatDate(entry.date)}</td>
                <td className={`whitespace-nowrap border-b border-slate-100 px-3 py-2 ${entry.isLate || entry.status === 'late' ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatTime(entry.timeIn)}
                </td>
                <td className={`whitespace-nowrap border-b border-slate-100 px-3 py-2 ${entry.lateMinutes ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatMinutes(entry.lateMinutes ?? 0)}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-slate-700">{formatTime(entry.timeOut)}</td>
                <td className={`whitespace-nowrap border-b border-slate-100 px-3 py-2 ${entry.undertimeMinutes ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatMinutes(entry.undertimeMinutes ?? 0)}
                </td>
                <td className={`whitespace-nowrap border-b border-slate-100 px-3 py-2 ${entry.excessMinutesBreak ? 'font-medium text-rose-700' : 'text-slate-700'}`}>
                  {formatMinutes(entry.excessMinutesBreak ?? 0)}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-slate-700" title="Potential overtime outside the 10:00 PM–6:00 AM night period">
                  {formatMinutes(entry.overtimeRequestStatus === 'APPROVED' ? entry.approvedRegularOvertimeMinutes ?? 0 : entry.regularOvertimeMinutes ?? 0)}
                  {entry.overtimeRequestStatus === 'APPROVED' ? ' approved'
                    : entry.regularOvertimeHours !== undefined && entry.regularOvertimeMinutes ? ` (${entry.regularOvertimeHours.toFixed(2)}h potential)` : ''}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-slate-700" title="Night-differential minutes excluding night-differential overtime">
                  {formatMinutes(getNonOvertimeNightDifferentialMinutes(entry))}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-slate-700" title="Potential overtime overlapping 10:00 PM–6:00 AM; approval is separate">
                  {formatMinutes(entry.overtimeRequestStatus === 'APPROVED' ? entry.approvedNightDifferentialOvertimeMinutes ?? 0 : entry.nightDifferentialOvertimeMinutes ?? 0)}
                  {entry.overtimeRequestStatus === 'APPROVED' ? ' approved'
                    : entry.nightDifferentialOvertimeHours !== undefined && entry.nightDifferentialOvertimeMinutes ? ` (${entry.nightDifferentialOvertimeHours.toFixed(2)}h potential)` : ''}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 text-slate-700" title="All hours worked from 10:00 PM to 6:00 AM, including scheduled hours">
                  {formatMinutes(entry.overtimeRequestStatus === 'APPROVED' ? entry.approvedNightDifferentialMinutes ?? 0 : entry.nightDifferentialMinutes ?? 0)}
                  {entry.overtimeRequestStatus === 'APPROVED' ? ' approved'
                    : entry.nightDifferentialHours !== undefined && entry.nightDifferentialMinutes ? ` (${entry.nightDifferentialHours.toFixed(2)}h potential)` : ''}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2 font-bold text-black" title={isUnderScheduledHours(entry) ? 'Below scheduled shift duration' : undefined}>
                  {formatHoursWorked(entry.minutesWorked)}
                </td>
                <td className="whitespace-nowrap border-b border-slate-100 px-3 py-2">
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                    entry.status === 'no-logout' ? 'bg-amber-50 text-amber-700'
                      : entry.status === 'no-login' ? 'bg-rose-50 text-rose-700'
                        : entry.status === 'on-leave' ? 'bg-slate-100 text-slate-600'
                          : 'bg-emerald-50 text-emerald-700'
                  }`}>
                    {entry.status === 'no-logout' ? 'No Logout' : entry.status === 'no-login' ? 'No Login' : entry.status === 'on-leave' ? 'On Leave' : 'Logout'}
                  </span>
                </td>
                <td className="min-w-48 border-b border-slate-100 px-3 py-2 align-top">
                  {(entry.overtimeApplications ?? []).map((application) => (
                    <p key={application.id} className={`text-xs leading-4 ${application.status === 'APPROVED' ? 'text-emerald-700' : application.status === 'REJECTED' ? 'text-rose-700' : 'text-amber-700'}`}>
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
      </div>}
    </div>
  )
}
