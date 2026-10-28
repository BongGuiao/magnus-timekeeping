import { useState, type FormEvent } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  fetchOrgUnitAttendanceSummary,
  type OrgUnitAttendanceSummary,
} from '../lib/attendanceReportApi'

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

function formatHours(minutes: number): string {
  return (minutes / 60).toFixed(2)
}

function OrgUnitAttendanceSummaryReport({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const today = new Date()
  const [fromDate, setFromDate] = useState(
    localDateValue(new Date(today.getFullYear(), today.getMonth(), 1)),
  )
  const [toDate, setToDate] = useState(localDateValue(today))
  const [summaries, setSummaries] = useState<OrgUnitAttendanceSummary[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [hasRun, setHasRun] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function runReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsLoading(true)
    setError(null)
    setHasRun(true)
    try {
      setSummaries(await fetchOrgUnitAttendanceSummary(fromDate, toDate))
    } catch (loadError: unknown) {
      setSummaries([])
      setError(loadError instanceof Error ? loadError.message : 'Could not load the Org Unit attendance summary.')
    } finally {
      setIsLoading(false)
    }
  }

  const totals = summaries.reduce(
    (result, summary) => ({
      total_attendance: result.total_attendance + summary.total_attendance,
      approved_leave_days: result.approved_leave_days + summary.approved_leave_days,
      approved_leave_minutes: result.approved_leave_minutes + summary.approved_leave_minutes,
      approved_overtime_count: result.approved_overtime_count + summary.approved_overtime_count,
      approved_overtime_minutes: result.approved_overtime_minutes + summary.approved_overtime_minutes,
      approved_ob_count: result.approved_ob_count + summary.approved_ob_count,
      approved_ob_minutes: result.approved_ob_minutes + summary.approved_ob_minutes,
      regular_overtime_minutes: result.regular_overtime_minutes + summary.regular_overtime_minutes,
      night_differential_minutes: result.night_differential_minutes + summary.night_differential_minutes,
      night_differential_overtime_minutes:
        result.night_differential_overtime_minutes + summary.night_differential_overtime_minutes,
      late_minutes: result.late_minutes + summary.late_minutes,
      undertime_minutes: result.undertime_minutes + summary.undertime_minutes,
    }),
    {
      total_attendance: 0,
      approved_leave_days: 0,
      approved_leave_minutes: 0,
      approved_overtime_count: 0,
      approved_overtime_minutes: 0,
      approved_ob_count: 0,
      approved_ob_minutes: 0,
      regular_overtime_minutes: 0,
      night_differential_minutes: 0,
      night_differential_overtime_minutes: 0,
      late_minutes: 0,
      undertime_minutes: 0,
    },
  )

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView="attendance-org-unit-summary"
        onNavigate={onNavigate}
        onSignOut={logout}
      />
      <main className="w-full px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">Attendance Summary by Org Unit</h1>
          <p className="mt-1 text-sm text-slate-600">
            Summary of attendance and approved leave, overtime, and official business for each Org Unit.
          </p>
        </header>

        <form
          onSubmit={(event) => void runReport(event)}
          className="mb-6 grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto]"
        >
          <label className="text-sm font-medium text-slate-700">
            From
            <input
              type="date"
              required
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm font-medium text-slate-700">
            To
            <input
              type="date"
              required
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <button
            type="submit"
            disabled={isLoading}
            className="self-end rounded-lg bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? 'Loading…' : 'Run report'}
          </button>
        </form>

        {error && (
          <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}
        {hasRun && !error && !isLoading && summaries.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-600">
            No Org Units or attendance activity were found for the selected dates.
          </div>
        )}
        {summaries.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full min-w-[1900px] border-collapse text-left text-sm">
              <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-3 py-3">Org Unit</th>
                  <th className="px-3 py-3">Employees</th>
                  <th className="px-3 py-3">Attendance</th>
                  <th className="px-3 py-3">Approved leave</th>
                  <th className="px-3 py-3">Approved OT</th>
                  <th className="px-3 py-3">Approved OB</th>
                  <th className="px-3 py-3">Regular OT</th>
                  <th className="px-3 py-3">Night diff</th>
                  <th className="px-3 py-3">ND OT</th>
                  <th className="px-3 py-3">Late</th>
                  <th className="px-3 py-3">Undertime</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {summaries.map((summary) => (
                  <tr key={summary.org_unit_id ?? 'unassigned'} className="align-top hover:bg-slate-50">
                    <th scope="row" className="px-3 py-3 text-left">
                      <div className="font-semibold text-slate-900">{summary.org_unit_name}</div>
                      <div className="text-xs text-slate-500">{summary.org_unit_code}</div>
                    </th>
                    <td className="px-3 py-3">{summary.employee_count}</td>
                    <td className="px-3 py-3">{summary.total_attendance}</td>
                    <td className="px-3 py-3">
                      {summary.approved_leave_days} day(s) · {formatHours(summary.approved_leave_minutes)} hrs
                    </td>
                    <td className="px-3 py-3">
                      {summary.approved_overtime_count} request(s) · {formatHours(summary.approved_overtime_minutes)} hrs
                    </td>
                    <td className="px-3 py-3">
                      {summary.approved_ob_count} request(s) · {formatHours(summary.approved_ob_minutes)} hrs
                    </td>
                    <td className="px-3 py-3">{formatHours(summary.regular_overtime_minutes)} hrs</td>
                    <td className="px-3 py-3">{formatHours(summary.night_differential_minutes)} hrs</td>
                    <td className="px-3 py-3">{formatHours(summary.night_differential_overtime_minutes)} hrs</td>
                    <td className="px-3 py-3">{formatHours(summary.late_minutes)} hrs</td>
                    <td className="px-3 py-3">{formatHours(summary.undertime_minutes)} hrs</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-slate-300 bg-slate-100 font-bold text-slate-900">
                  <th scope="row" className="px-3 py-3 text-left">Total</th>
                  <td className="px-3 py-3">—</td>
                  <td className="px-3 py-3">{totals.total_attendance}</td>
                  <td className="px-3 py-3">
                    {totals.approved_leave_days} day(s) · {formatHours(totals.approved_leave_minutes)} hrs
                  </td>
                  <td className="px-3 py-3">
                    {totals.approved_overtime_count} request(s) · {formatHours(totals.approved_overtime_minutes)} hrs
                  </td>
                  <td className="px-3 py-3">
                    {totals.approved_ob_count} request(s) · {formatHours(totals.approved_ob_minutes)} hrs
                  </td>
                  <td className="px-3 py-3">{formatHours(totals.regular_overtime_minutes)} hrs</td>
                  <td className="px-3 py-3">{formatHours(totals.night_differential_minutes)} hrs</td>
                  <td className="px-3 py-3">{formatHours(totals.night_differential_overtime_minutes)} hrs</td>
                  <td className="px-3 py-3">{formatHours(totals.late_minutes)} hrs</td>
                  <td className="px-3 py-3">{formatHours(totals.undertime_minutes)} hrs</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Attendance counts valid attendance records. Approved requests are counted by their effective attendance or request date. Hours are shown as decimal hours.
        </p>
      </main>
    </div>
  )
}

export default OrgUnitAttendanceSummaryReport
