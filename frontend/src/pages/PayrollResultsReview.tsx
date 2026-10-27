import { useCallback, useEffect, useState } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  fetchOrganizationPayrollCutoffResults,
  fetchMyPayrollCutoffResults,
  fetchMyTeamPayrollCutoffResults,
} from '../lib/payrollCutoffApi'
import type { EmployeeCutoffResult } from '../lib/payrollCutoffApi'
import { getSelectedDashboardRole } from '../types/role'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function formatMinutes(minutes: number) {
  return `${(minutes / 60).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} hr`
}

function ResultTable({ rows }: { rows: EmployeeCutoffResult[] }) {
  if (rows.length === 0) {
    return <p className="px-5 py-6 text-sm text-slate-500">No payroll calculations to review.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-[1900px] w-full text-left text-xs">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-3">Employee</th>
            <th className="px-3 py-3">Scheduled days</th>
            <th className="px-3 py-3">Paid days</th>
            <th className="px-3 py-3">Regular</th>
            <th className="px-3 py-3">Late</th>
            <th className="px-3 py-3">Undertime</th>
            <th className="px-3 py-3">Absence</th>
            <th className="px-3 py-3">Paid leave</th>
            <th className="px-3 py-3">Unpaid leave</th>
            <th className="px-3 py-3">Ordinary OT</th>
            <th className="px-3 py-3">Official business</th>
            <th className="px-3 py-3">Rest day</th>
            <th className="px-3 py-3">Rest day OT</th>
            <th className="px-3 py-3">Special day</th>
            <th className="px-3 py-3">Special day OT</th>
            <th className="px-3 py-3">Holiday</th>
            <th className="px-3 py-3">Holiday OT</th>
            <th className="px-3 py-3">Night regular</th>
            <th className="px-3 py-3">Night OT</th>
            <th className="px-3 py-3">Exceptions</th>
            <th className="px-3 py-3">Payroll</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => {
            return (
              <tr key={row.id}>
                <td className="whitespace-nowrap px-3 py-3">
                  <p className="font-medium text-slate-800">{row.employee_name || 'Employee name unavailable'}</p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {row.cutoff_code ? `Cutoff ${row.cutoff_code}` : `Cutoff ${row.cutoff_id}`}
                  </p>
                  {row.period_start && row.period_end && (
                    <p className="text-[11px] text-slate-500">{row.period_start} → {row.period_end}</p>
                  )}
                </td>
                <td className="px-3 py-3">{row.scheduled_days.toLocaleString()}</td>
                <td className="px-3 py-3">{row.paid_days.toLocaleString()}</td>
                <td className="px-3 py-3">{formatMinutes(row.regular_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.late_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.undertime_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.absence_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.paid_leave_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.unpaid_leave_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.ordinary_ot_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.official_business_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.rest_day_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.rest_day_ot_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.special_day_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.special_day_ot_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.holiday_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.holiday_ot_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.night_regular_minutes)}</td>
                <td className="px-3 py-3">{formatMinutes(row.night_ot_minutes)}</td>
                <td className="px-3 py-3">{row.exception_count}</td>
                <td className="px-3 py-3">{row.payroll_status}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function PayrollResultsReview({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const selectedRole = getSelectedDashboardRole()
  const reportScope = selectedRole === 'employee'
    ? 'own'
    : selectedRole === 'supervisor'
      ? 'team'
      : 'organization'
  const scopeTitle = reportScope === 'own'
    ? 'My calculations'
    : reportScope === 'team'
      ? 'My team’s calculations'
      : 'Organization calculations'
  const [results, setResults] = useState<EmployeeCutoffResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadResults = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = reportScope === 'own'
        ? await fetchMyPayrollCutoffResults()
        : reportScope === 'team'
          ? await fetchMyTeamPayrollCutoffResults()
          : await fetchOrganizationPayrollCutoffResults()
      setResults(data)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load payroll results for review.')
    } finally {
      setLoading(false)
    }
  }, [reportScope])

  useEffect(() => {
    void loadResults()
  }, [loadResults])

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="payroll-review" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Payroll Calculation Review</h1>
            <p className="mt-1 text-xs text-slate-600">View-only cutoff totals. Attendance is frozen once the cutoff's attendance deadline passes, and HR approves the final payroll.</p>
          </div>
          <button
            type="button"
            onClick={() => onNavigate?.('dashboard')}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700"
          >
            Back to dashboard
          </button>
        </header>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-5 py-3">
            <h2 className="text-sm font-bold text-slate-900">{scopeTitle}</h2>
            <p className="text-xs text-slate-500">View-only cutoff totals. Raise corrections with HR before the cutoff's attendance deadline.</p>
          </div>
          {loading ? <p role="status" className="px-5 py-6 text-xs text-slate-500">Loading results…</p> : (
            <ResultTable rows={results} />
          )}
        </section>
      </main>
    </div>
  )
}
