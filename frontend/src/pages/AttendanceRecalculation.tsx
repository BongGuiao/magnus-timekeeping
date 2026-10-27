import { useEffect, useState, type FormEvent } from 'react'
import { AlertTriangle, Calculator, RefreshCw } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  fetchCurrentAttendancePayrollCutoff,
  fetchSupervisorTeamEmployees,
  recalculateAttendanceRange,
  type SupervisorTeamEmployee,
  type AttendanceRangeRecalculationResult,
} from '../lib/attendanceApi'
import { fetchEmployees } from '../lib/employeeApi'
import type { Employee } from '../types/employee'
import { getSelectedDashboardRole, normalizeDashboardRole } from '../types/role'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function localDateValue(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 10)
}

function employeeLabel(employee: Employee): string {
  const name = employee.preferred_name || [employee.first_name, employee.last_name].filter(Boolean).join(' ')
  return `${employee.employee_no} — ${name}`
}

function formatPunch(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatMinutes(minutes: number): string {
  if (minutes <= 0) return '—'
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return hours ? `${hours}h ${remainingMinutes}m` : `${remainingMinutes}m`
}

function statusClass(status: string): string {
  switch (status) {
    case 'UPDATED':
      return 'bg-emerald-100 text-emerald-800'
    case 'PREVIEW':
      return 'bg-indigo-100 text-indigo-800'
    case 'SKIPPED':
      return 'bg-amber-100 text-amber-800'
    default:
      return 'bg-slate-100 text-slate-700'
  }
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

export default function AttendanceRecalculation({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const today = localDateValue(new Date())
  const [employees, setEmployees] = useState<Employee[]>([])
  const [teamEmployees, setTeamEmployees] = useState<SupervisorTeamEmployee[]>([])
  const [employeeId, setEmployeeId] = useState('')
  const [fromDate, setFromDate] = useState(today)
  const [toDate, setToDate] = useState(today)
  const [results, setResults] = useState<AttendanceRangeRecalculationResult[] | null>(null)
  const [isLoadingEmployees, setIsLoadingEmployees] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const isAdmin = normalizeDashboardRole(localStorage.getItem('role')) === 'administrator'
  const isEmployeeView = getSelectedDashboardRole() === 'employee'
  const isSupervisorView = getSelectedDashboardRole() === 'supervisor'
  const employeeCode = localStorage.getItem('employee_code')?.trim().toUpperCase() ?? ''

  useEffect(() => {
    let current = true
    const shouldLoadCutoff = isSupervisorView || isEmployeeView
    setIsLoadingEmployees(shouldLoadCutoff || (isAdmin && !isEmployeeView))
    const loadEmployees = isSupervisorView
      ? fetchSupervisorTeamEmployees().then((items) => {
        if (current) setTeamEmployees(items)
      })
      : isAdmin && !isEmployeeView
        ? fetchEmployees().then((items) => {
          if (!current) return
          const activeEmployees = items.filter((item) => item.is_active && item.record_status === 'ACTIVE')
          setEmployees(activeEmployees)
          setEmployeeId(activeEmployees[0]?.id ?? '')
        })
        : Promise.resolve()
    const loadCutoff = shouldLoadCutoff
      ? fetchCurrentAttendancePayrollCutoff().then((cutoff) => {
        if (!current) return
        setFromDate(cutoff.period_start)
        setToDate(cutoff.period_end)
      })
      : Promise.resolve()
    Promise.all([loadEmployees, loadCutoff])
      .catch((cause: unknown) => {
        if (current) {
          setError(cause instanceof Error ? cause.message : 'Could not load attendance recalculation defaults.')
        }
      })
      .finally(() => {
        if (current) setIsLoadingEmployees(false)
      })
    return () => {
      current = false
    }
  }, [isAdmin, isEmployeeView, isSupervisorView])

  function clearResult() {
    setResults(null)
    setSuccess('')
  }

  async function runRecalculation(dryRun: boolean) {
    const scope = isSupervisorView ? 'team' : isEmployeeView ? 'own' : 'employee'
    if (
      (scope === 'employee' && !employeeId)
      || (scope === 'team' && teamEmployees.length === 0)
      || (scope === 'own' && !employeeCode)
      || !fromDate
      || !toDate
      || fromDate > toDate
    ) {
      setError('Select a valid employee scope and inclusive date range.')
      return
    }
    setError('')
    setSuccess('')
    setIsSubmitting(true)
    try {
      const response = await recalculateAttendanceRange({
        scope,
        ...(scope === 'employee' ? { employee_id: employeeId } : {}),
        from_date: fromDate,
        to_date: toDate,
        dry_run: dryRun,
      })
      setResults(response)
      if (!dryRun) {
        const updated = response.reduce((total, result) => total + result.updated_count, 0)
        const unchanged = response.reduce((total, result) => total + result.unchanged_count, 0)
        const skipped = response.reduce((total, result) => total + result.skipped_count, 0)
        setSuccess(
          `Recalculation completed for ${response.length} employee(s): ${updated} updated, `
          + `${unchanged} unchanged, ${skipped} skipped.`,
        )
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not recalculate attendance.')
    } finally {
      setIsSubmitting(false)
    }
  }

  function handlePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void runRecalculation(true)
  }

  function handleApply() {
    if (!results?.some((result) => result.dry_run && result.preview_count > 0)) return
    const previewCount = results.reduce((total, result) => total + result.preview_count, 0)
    const selectedEmployee = employees.find((item) => item.id === employeeId)
    const targetLabel = isSupervisorView
      ? `${teamEmployees.length} direct report(s)`
      : isEmployeeView
        ? employeeCode
        : selectedEmployee
          ? employeeLabel(selectedEmployee)
          : 'the selected employee'
    const confirmed = window.confirm(
      `Apply recalculation to ${previewCount} attendance record(s) for `
      + `${targetLabel}`
      + ` from ${fromDate} through ${toDate}? `
      + 'This will save attendance and overtime/night differential changes.',
    )
    if (confirmed) void runRecalculation(false)
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView="attendance-recalculation"
        onNavigate={onNavigate}
        onSignOut={logout}
      />
      <main className="mx-auto w-[95%] max-w-7xl py-8">
        <div className="mb-6">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-indigo-600">Timekeeping</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Attendance recalculation</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Recalculate attendance lateness, undertime, overtime, and night differential from the
            employee&apos;s saved schedule boundaries and punches. Expected times remain schedule-based.
          </p>
        </div>

        {!isAdmin && !isEmployeeView && !isSupervisorView ? (
          <section className="rounded-2xl border border-rose-200 bg-white p-6 text-sm text-rose-800 shadow-sm">
            Switch to Employee or Supervisor mode to recalculate attendance.
          </section>
        ) : (
          <>
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="mb-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
                <p className="text-sm">
                  Dates refer to attendance <strong>work dates</strong>, inclusive. Applying changes
                  will save recalculated values. Locked records, records with incomplete schedule or
                  punch data, and records with overtime applications are skipped.
                </p>
              </div>

              <form onSubmit={handlePreview} className="grid gap-4 md:grid-cols-4 md:items-end">
                {isEmployeeView ? (
                  <p className="text-sm font-semibold text-slate-700 md:col-span-2">
                    Employee
                    <span className={`${inputClass} block bg-slate-50`}>
                      {employeeCode || 'No employee code linked'}
                    </span>
                  </p>
                ) : isSupervisorView ? (
                  <p className="text-sm font-semibold text-slate-700 md:col-span-2">
                    Employees
                    <span className={`${inputClass} block bg-slate-50`}>
                      {isLoadingEmployees ? 'Loading direct reports…' : `All ${teamEmployees.length} active direct report(s)`}
                    </span>
                  </p>
                ) : (
                  <label className="text-sm font-semibold text-slate-700 md:col-span-2">
                    Employee
                    <select
                      required
                      value={employeeId}
                      disabled={isLoadingEmployees || employees.length === 0 || isSubmitting}
                      onChange={(event) => {
                        setEmployeeId(event.target.value)
                        clearResult()
                      }}
                      className={inputClass}
                    >
                      <option value="">
                        {isLoadingEmployees ? 'Loading employees…' : 'Select an employee'}
                      </option>
                      {employees.map((employee) => (
                        <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
                      ))}
                    </select>
                  </label>
                )}
                <label className="text-sm font-semibold text-slate-700">
                  From work date
                  <input
                    required
                    type="date"
                    value={fromDate}
                    disabled={isSubmitting}
                    onChange={(event) => {
                      setFromDate(event.target.value)
                      clearResult()
                    }}
                    className={inputClass}
                  />
                </label>
                <label className="text-sm font-semibold text-slate-700">
                  To work date
                  <input
                    required
                    type="date"
                    min={fromDate || undefined}
                    value={toDate}
                    disabled={isSubmitting}
                    onChange={(event) => {
                      setToDate(event.target.value)
                      clearResult()
                    }}
                    className={inputClass}
                  />
                </label>
                <div className="md:col-span-4 md:flex md:justify-end">
                  <button
                    type="submit"
                    disabled={
                      isLoadingEmployees
                      || isSubmitting
                      || (isSupervisorView && teamEmployees.length === 0)
                      || (isEmployeeView && !employeeCode)
                      || (!isSupervisorView && !isEmployeeView && employees.length === 0)
                      || (!isSupervisorView && !isEmployeeView && !employeeId)
                    }
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 md:w-auto"
                  >
                    {isSubmitting
                      ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                      : <Calculator className="h-4 w-4" aria-hidden="true" />}
                    Preview recalculation
                  </button>
                </div>
              </form>
              {!isLoadingEmployees && !isSupervisorView && !isEmployeeView && employees.length === 0 && !error && (
                <p className="mt-3 text-sm text-slate-500">No active employees are available.</p>
              )}
              {isSupervisorView && teamEmployees.length === 0 && !isLoadingEmployees && !error && (
                <p className="mt-3 text-sm text-slate-500">No active direct reports are assigned to your account.</p>
              )}
              {isEmployeeView && !employeeCode && !isLoadingEmployees && (
                <p role="alert" className="mt-3 text-sm text-amber-800">
                  Your account is not linked to an active employee record, so recalculation cannot run in Employee view.
                </p>
              )}
            </section>

            {error && (
              <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                {error}
              </p>
            )}
            {success && (
              <p role="status" className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                {success}
              </p>
            )}

            {results && results.map((result, index) => {
              const employee = employees.find((item) => item.id === result.employee_id)
              const teamEmployee = teamEmployees.find((item) => item.employee_id === result.employee_id)
              const employeeTitle = isEmployeeView
                ? `${employeeCode} — ${employeeName}`
                : teamEmployee
                  ? `${teamEmployee.employee_code} — ${teamEmployee.employee_name}`
                  : employee
                    ? employeeLabel(employee)
                    : result.employee_id
              return (
              <section key={result.employee_id} className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="flex flex-col gap-4 border-b border-slate-200 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="text-lg font-bold text-slate-900">
                      {employeeTitle} — {result.dry_run ? 'Preview results' : 'Recalculation results'}
                    </h2>
                    <p className="mt-1 text-sm text-slate-500">
                      {result.from_date} through {result.to_date} · {result.records.length} attendance record(s)
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
                      {result.dry_run && <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-indigo-800">{result.preview_count} to update</span>}
                      {!result.dry_run && <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-emerald-800">{result.updated_count} updated</span>}
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">{result.unchanged_count} unchanged</span>
                      <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-800">{result.skipped_count} skipped</span>
                    </div>
                  </div>
                  {index === 0 && results.some((item) => item.dry_run && item.preview_count > 0) && (
                    <button
                      type="button"
                      disabled={isSubmitting}
                      onClick={handleApply}
                      className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                      Apply recalculation
                    </button>
                  )}
                </div>
                {result.records.length === 0 ? (
                  <p className="p-6 text-sm text-slate-500">No valid attendance records were found in this work-date range.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                      <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                        <tr>
                          <th className="px-4 py-3 font-semibold">Work date</th>
                          <th className="px-4 py-3 font-semibold">Status</th>
                          <th className="px-4 py-3 font-semibold">Actual in</th>
                          <th className="px-4 py-3 font-semibold">Actual out</th>
                          <th className="px-4 py-3 font-semibold">Expected in</th>
                          <th className="px-4 py-3 font-semibold">Expected out</th>
                          <th className="px-4 py-3 font-semibold">Hours worked</th>
                          <th className="px-4 py-3 font-semibold">Break details</th>
                          <th className="px-4 py-3 font-semibold">Break excess</th>
                          <th className="px-4 py-3 font-semibold">Regular OT</th>
                          <th className="px-4 py-3 font-semibold">OT ND</th>
                          <th className="px-4 py-3 font-semibold">Total OT</th>
                          <th className="px-4 py-3 font-semibold">Non-OT ND</th>
                          <th className="px-4 py-3 font-semibold">Late</th>
                          <th className="px-4 py-3 font-semibold">Undertime</th>
                          <th className="px-4 py-3 font-semibold">Notes</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {result.records.map((record) => (
                          <tr key={record.attendance_id} className="align-top">
                            <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-900">{record.work_date}</td>
                            <td className="px-4 py-3">
                              <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${statusClass(record.status)}`}>
                                {record.status}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatPunch(record.actual_clock_in_at)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatPunch(record.actual_clock_out_at)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatPunch(record.expected_clock_in_at)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatPunch(record.expected_clock_out_at)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{record.minutes_worked == null ? '—' : formatMinutes(record.minutes_worked)}</td>
                            <td className="min-w-56 px-4 py-3 text-xs text-slate-700">
                              {record.break_calculation_details.length
                                ? record.break_calculation_details.map((breakDetail) => (
                                  <p key={breakDetail.break_slot}>
                                    {breakDetail.break_slot.replaceAll('_', ' ')}: {formatPunch(breakDetail.punch_out_at)}
                                    {'–'}{formatPunch(breakDetail.punch_in_at)}
                                    {' · '}{breakDetail.duration_minutes ?? '—'} min
                                    {' / allowance '}{breakDetail.allowance_minutes ?? '—'} min
                                    {' / excess '}{breakDetail.excess_minutes} min
                                  </p>
                                ))
                                : 'No configured or punched breaks'}
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatMinutes(record.excess_minutes_break)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatMinutes(record.regular_overtime_minutes)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatMinutes(record.night_differential_overtime_minutes)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatMinutes(record.calculated_ot_minutes)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatMinutes(record.regular_night_differential_minutes)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">
                              {formatMinutes(record.previous_late_minutes)} → {formatMinutes(record.late_minutes)}
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatMinutes(record.undertime_minutes)}</td>
                            <td className="min-w-56 px-4 py-3 text-xs text-slate-600">{record.reason ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
              )
            })}
          </>
        )}
      </main>
    </div>
  )
}
