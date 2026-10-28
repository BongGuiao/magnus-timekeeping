import { Fragment, useEffect, useState, type FormEvent } from 'react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import {
  finalizeAttendanceCutoff,
  fetchAttendanceFinalizationCutoffs,
  fetchAttendanceDetailReport,
  type AttendanceFinalizationCutoff,
  type AttendanceDetailReportFilters,
  type AttendanceDetailReportRecord,
} from '../lib/attendanceReportApi'
import { getSelectedDashboardRole, hasAnyPermission, hasPermission } from '../types/role'

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

function formatReportDate(value: string): string {
  const [year, month, day] = value.split('-')
  return `${month}-${day}-${year}`
}

function formatHours(value: number | null | undefined): string {
  return value == null ? '—' : `${(value / 60).toFixed(2)} hrs`
}

function approvedOvertimeMinutes(record: AttendanceDetailReportRecord): number {
  return record.overtime_applications.reduce(
    (total, overtime) =>
      total
      + (overtime.status === 'APPROVED'
        ? overtime.payable_minutes ?? overtime.approved_minutes ?? 0
        : 0),
    0,
  )
}

function AttendanceDetailReport({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const today = new Date()
  const defaultFrom = localDateValue(new Date(today.getFullYear(), today.getMonth(), 1))
  const defaultTo = localDateValue(today)
  const employeeCode = localStorage.getItem('employee_code') ?? ''
  const selectedRole = getSelectedDashboardRole()
  const isEmployeeView = selectedRole === 'employee'
  const reportScope: AttendanceDetailReportFilters['scope'] = selectedRole === 'employee'
    ? 'own'
    : selectedRole === 'supervisor'
      ? 'team'
      : 'organization'
  const canFinalizeAttendance = hasPermission('attendance.finalize')
  const canReviewCutoffStatus = hasAnyPermission(['attendance.read_org', 'payroll.manage'])
  const [fromDate, setFromDate] = useState(defaultFrom)
  const [toDate, setToDate] = useState(defaultTo)
  const [employeeNo, setEmployeeNo] = useState(isEmployeeView ? employeeCode : '')
  const [query, setQuery] = useState({
    from_date: defaultFrom,
    to_date: defaultTo,
    scope: reportScope,
    employee_no: isEmployeeView ? employeeCode : '',
    cutoff_id: '',
  })
  const [records, setRecords] = useState<AttendanceDetailReportRecord[]>([])
  const [attendanceCutoffs, setAttendanceCutoffs] = useState<AttendanceFinalizationCutoff[]>([])
  const [selectedAttendanceCutoffId, setSelectedAttendanceCutoffId] = useState('')
  const [finalizationLoading, setFinalizationLoading] = useState(false)
  const [finalizationError, setFinalizationError] = useState<string | null>(null)
  const [finalizationNotice, setFinalizationNotice] = useState<string | null>(null)
  const [currentTime, setCurrentTime] = useState(Date.now())
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const daysWithPunches = records.filter((record) => record.clock_in_at && record.clock_out_at).length
  const totalRegularMinutes = records.reduce((total, record) => total + (record.worked_minutes ?? 0), 0)
  const totalPotentialOvertimeMinutes = records.reduce(
    (total, record) => total + record.regular_overtime_minutes + record.night_differential_overtime_minutes,
    0,
  )
  const totalNightDifferentialMinutes = records.reduce(
    (total, record) => total + record.night_differential_minutes,
    0,
  )
  const totalLateAndUndertimeMinutes = records.reduce(
    (total, record) => total + record.late_minutes + record.undertime_minutes,
    0,
  )
  const selectedAttendanceCutoff = attendanceCutoffs.find(
    (cutoff) => cutoff.cutoff_id === selectedAttendanceCutoffId,
  )
  const attendanceDeadlinePassed = Boolean(
    selectedAttendanceCutoff?.attendance_deadline
      && currentTime > new Date(selectedAttendanceCutoff.attendance_deadline).getTime(),
  )
  const canFinalizeSelectedCutoff = Boolean(
    selectedAttendanceCutoff
      && !selectedAttendanceCutoff.attendance_finalized_at
      && selectedAttendanceCutoff.attendance_deadline
      && attendanceDeadlinePassed
      && selectedAttendanceCutoff.attendance_result_count > 0,
  )

  useEffect(() => {
    const timerId = window.setInterval(() => setCurrentTime(Date.now()), 30_000)
    return () => window.clearInterval(timerId)
  }, [])

  useEffect(() => {
    if (!canReviewCutoffStatus) return
    let isCurrent = true
    fetchAttendanceFinalizationCutoffs()
      .then((cutoffs) => {
        if (!isCurrent) return
        setAttendanceCutoffs(cutoffs)
        const selected = cutoffs[0]
        setSelectedAttendanceCutoffId(selected?.cutoff_id ?? '')
        if (selected) {
          setFromDate(selected.period_start)
          setToDate(selected.period_end)
          setQuery({
            from_date: selected.period_start,
            to_date: selected.period_end,
            scope: reportScope,
            employee_no: '',
            cutoff_id: selected.cutoff_id,
          })
        }
      })
      .catch((loadError: unknown) => {
        if (isCurrent) {
          setFinalizationError(
            loadError instanceof Error
              ? loadError.message
              : 'Could not load attendance cutoff status.',
          )
        }
      })
    return () => {
      isCurrent = false
    }
  }, [canReviewCutoffStatus, reportScope])

  useEffect(() => {
    let isCurrent = true
    setIsLoading(true)
    setError(null)
    fetchAttendanceDetailReport(query)
      .then((result) => {
        if (isCurrent) setRecords(result)
      })
      .catch((loadError: unknown) => {
        if (isCurrent) {
          setRecords([])
          setError(loadError instanceof Error ? loadError.message : 'Could not load attendance report.')
        }
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [query])

  function runReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setQuery({
      from_date: fromDate,
      to_date: toDate,
      scope: reportScope,
      employee_no: isEmployeeView ? employeeCode : employeeNo.trim(),
      cutoff_id: selectedAttendanceCutoffId,
    })
  }

  function updateReportDate(field: 'from' | 'to', value: string) {
    const nextFromDate = field === 'from' ? value : fromDate
    const nextToDate = field === 'to' ? value : toDate
    if (field === 'from') setFromDate(value)
    else setToDate(value)

    const matchingCutoff = attendanceCutoffs.find(
      (cutoff) => cutoff.period_start === nextFromDate && cutoff.period_end === nextToDate,
    )
    setSelectedAttendanceCutoffId(matchingCutoff?.cutoff_id ?? '')
  }

  function selectFinalizationCutoff(cutoffId: string) {
    setSelectedAttendanceCutoffId(cutoffId)
    setFinalizationError(null)
    setFinalizationNotice(null)
    if (!cutoffId) return
    const cutoff = attendanceCutoffs.find((item) => item.cutoff_id === cutoffId)
    if (!cutoff) return
    setFromDate(cutoff.period_start)
    setToDate(cutoff.period_end)
    setQuery({
      from_date: cutoff.period_start,
      to_date: cutoff.period_end,
      scope: reportScope,
      employee_no: '',
      cutoff_id: cutoff.cutoff_id,
    })
  }

  async function finalizeAttendance() {
    if (!selectedAttendanceCutoff || !canFinalizeSelectedCutoff || !canFinalizeAttendance) return
    setFinalizationLoading(true)
    setFinalizationError(null)
    setFinalizationNotice(null)
    try {
      const result = await finalizeAttendanceCutoff(selectedAttendanceCutoff.cutoff_id)
      setAttendanceCutoffs((current) => current.map((cutoff) => (
        cutoff.cutoff_id === result.cutoff_id
          ? {
            ...cutoff,
            attendance_finalized_at: result.finalized_at,
            attendance_finalized_by: result.finalized_by,
            attendance_result_count: result.attendance_result_count,
          }
          : cutoff
      )))
      setFinalizationNotice(
        `Attendance for ${selectedAttendanceCutoff.cutoff_code} is finalized. Payroll calculation can now proceed.`,
      )
    } catch (cause) {
      setFinalizationError(
        cause instanceof Error ? cause.message : 'Could not finalize attendance for this cutoff.',
      )
    } finally {
      setFinalizationLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView="attendance-detail-report"
        onNavigate={onNavigate}
        onSignOut={logout}
      />
      <main className="w-full px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">Attendance Detail</h1>
          <p className="mt-1 text-sm text-slate-600">
            Review scheduled workdays, punches, leave, overtime, night differential, and official business.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Time values are shown in hours. Potential overtime and night differential are attendance-based estimates,
            not confirmed payable amounts. Approved overtime requests are listed separately.
          </p>
        </header>

        {(canReviewCutoffStatus || !canFinalizeAttendance) && (
          <section className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900">Attendance cutoff finalization</h2>
            <p className="mt-1 text-xs text-slate-600">
              Review and calculate attendance results before finalizing. Finalized attendance cannot be changed;
              payroll calculation is enabled only afterward.
            </p>
            {!canReviewCutoffStatus && (
              <p className="mt-3 text-xs text-amber-800">
                You can view attendance, but cutoff status and finalization are restricted to organization-level reviewers.
              </p>
            )}
            {canReviewCutoffStatus && (
              <div className="mt-3 flex flex-wrap items-end gap-3">
              <label className="min-w-72 flex-1 text-sm font-medium text-slate-700">
                Payroll cutoff
                <select
                  value={selectedAttendanceCutoffId}
                  onChange={(event) => selectFinalizationCutoff(event.target.value)}
                  disabled={attendanceCutoffs.length === 0 || finalizationLoading}
                  className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                >
                  <option value="">
                    {attendanceCutoffs.length === 0 ? 'No active payroll cutoffs' : 'Custom date range'}
                  </option>
                  {attendanceCutoffs.map((cutoff) => (
                      <option key={cutoff.cutoff_id} value={cutoff.cutoff_id}>
                        {cutoff.cutoff_code} · {cutoff.payroll_group_name} · {cutoff.period_start} to {cutoff.period_end}
                      </option>
                  ))}
                </select>
              </label>
              {selectedAttendanceCutoff && (
                <div className="min-w-56 text-xs text-slate-600">
                  <p>
                    Status:{' '}
                    <span className="font-semibold">
                      {selectedAttendanceCutoff.attendance_finalized_at ? 'Attendance finalized' : 'Attendance open'}
                    </span>
                  </p>
                  <p>Attendance results: {selectedAttendanceCutoff.attendance_result_count} employee(s)</p>
                </div>
              )}
              <button
                type="button"
                onClick={() => void finalizeAttendance()}
                disabled={
                  !canFinalizeAttendance
                  || !canFinalizeSelectedCutoff
                  || finalizationLoading
                }
                title={
                  !canFinalizeAttendance
                    ? 'You do not have permission to finalize attendance.'
                    : !selectedAttendanceCutoff?.attendance_deadline
                      ? 'Set the cutoff attendance deadline first.'
                      : !attendanceDeadlinePassed
                        ? 'The attendance deadline must pass before finalization.'
                        : selectedAttendanceCutoff.attendance_result_count === 0
                          ? 'Calculate attendance results before finalization.'
                          : selectedAttendanceCutoff.attendance_finalized_at
                            ? 'Attendance is already finalized.'
                            : undefined
                }
                className="rounded-lg bg-indigo-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {finalizationLoading ? 'Finalizing…' : 'Finalize attendance'}
              </button>
              </div>
            )}
            {!canFinalizeAttendance && (
              <p className="mt-2 text-xs text-amber-800">
                You can review cutoff status, but only users with attendance finalization permission can finalize it.
              </p>
            )}
            {finalizationError && (
              <p role="alert" className="mt-3 text-sm text-rose-700">{finalizationError}</p>
            )}
            {finalizationNotice && (
              <p role="status" className="mt-3 text-sm text-emerald-700">{finalizationNotice}</p>
            )}
          </section>
        )}

        <form
          onSubmit={runReport}
          className="mb-6 grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1.2fr_auto]"
        >
          <label className="text-sm font-medium text-slate-700">
            From
            <input
              type="date"
              required
              value={fromDate}
              onChange={(event) => updateReportDate('from', event.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm font-medium text-slate-700">
            To
            <input
              type="date"
              required
              value={toDate}
              onChange={(event) => updateReportDate('to', event.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm font-medium text-slate-700">
            {isEmployeeView ? 'Your employee number' : 'Employee number (optional)'}
            <input
              type="text"
              value={employeeNo}
              onChange={(event) => {
                if (!isEmployeeView) setEmployeeNo(event.target.value)
              }}
              disabled={isEmployeeView}
              placeholder={isEmployeeView ? 'Employee number unavailable' : 'All employees'}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <button
            type="submit"
            disabled={isLoading || (isEmployeeView && !employeeCode)}
            className="self-end rounded-lg bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? 'Loading…' : 'Run report'}
          </button>
        </form>

        {isEmployeeView && !employeeCode && (
          <div role="alert" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Your account is not linked to an employee number, so the report cannot be filtered to your records.
            Contact an administrator to update your employee account.
          </div>
        )}
        {error && (
          <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}
        {!error && records.length > 0 && (
          <section aria-label="Attendance totals" className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-sm text-slate-500">Days with complete punches</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">{daysWithPunches}</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-sm text-slate-500">Regular hours worked</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">{formatHours(totalRegularMinutes)}</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-sm text-slate-500">Potential overtime hours</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">
                {formatHours(totalPotentialOvertimeMinutes)}
              </div>
              <div className="mt-1 text-xs text-slate-500">Includes regular and night-differential overtime.</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-sm text-slate-500">Night differential hours</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">
                {formatHours(totalNightDifferentialMinutes)}
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-sm text-slate-500">Total late + undertime</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">
                {formatHours(totalLateAndUndertimeMinutes)}
              </div>
            </div>
          </section>
        )}
        {!error && !isLoading && records.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-600">
            No attendance records found for the selected dates and employee.
          </div>
        )}

        {records.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full min-w-[1900px] table-fixed border-collapse text-left text-sm">
              <colgroup>
                <col className="w-[115px]" />
                <col className="w-[180px]" />
                <col className="w-[175px]" />
                <col className="w-[205px]" />
                <col className="w-[80px]" />
                <col className="w-[80px]" />
                <col className="w-[230px]" />
                <col className="w-[240px]" />
                <col className="w-[320px]" />
                <col className="w-[270px]" />
              </colgroup>
              <thead className="sticky top-0 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-4 py-3">Work date</th>
                  <th className="px-4 py-3">Employee</th>
                  <th className="px-4 py-3">Schedule</th>
                  <th className="px-4 py-3">Actual punches</th>
                  <th className="px-4 py-3">Work type</th>
                  <th className="px-4 py-3">Day type</th>
                  <th className="px-4 py-3">Attendance</th>
                  <th className="px-4 py-3">Worked / exceptions</th>
                  <th className="px-4 py-3">Potential overtime &amp; night diff</th>
                  <th className="px-4 py-3">Leave, overtime &amp; OB</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {records.map((record, index) => {
                  const isNewEmployee = index === 0
                    || records[index - 1].employee_no !== record.employee_no
                  return (
                    <Fragment key={`${record.employee_no}-${record.work_date}`}>
                      {isNewEmployee && (
                        <tr className="border-t-2 border-slate-300 bg-slate-100">
                          <th
                            colSpan={10}
                            scope="rowgroup"
                            className="px-4 py-2 text-left text-sm font-bold text-slate-800"
                          >
                            {record.employee_no} · {record.employee_name}
                          </th>
                        </tr>
                      )}
                      <tr
                        key={record.attendance_id ?? `${record.employee_no}-${record.work_date}-record`}
                        className={record.attendance_id ? 'align-top hover:bg-slate-50' : 'align-top bg-amber-50/50'}
                      >
                    <td className="px-4 py-3 font-medium">
                      <div className="whitespace-nowrap">{formatReportDate(record.work_date)}</div>
                    </td>
                    <td className="break-words px-4 py-3" title={`${record.employee_no} · ${record.employee_name}`}>
                      <div className="line-clamp-2">
                        <span className="font-semibold text-slate-900">{record.employee_no}</span>
                        <br />
                        {record.employee_name}
                      </div>
                    </td>
                    <td className="break-words px-4 py-3">
                      <div className="line-clamp-2">{record.schedule_code ?? '—'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="line-clamp-2 whitespace-nowrap">
                        {formatTime(record.clock_in_at)} – {formatTime(record.clock_out_at)}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="line-clamp-2">{record.work_type || '—'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="line-clamp-2">{record.day_type || '—'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div>
                        <div className={
                          record.attendance_id && record.record_status !== 'VALID'
                            ? 'font-semibold text-rose-700'
                            : ''
                        }>
                          {record.attendance_mode === 'SCHEDULE_CREDITED'
                            ? 'Schedule credited · no punch required'
                            : !record.attendance_id
                            ? 'No punches'
                            : record.is_absent
                            ? 'Absent'
                            : record.work_type === 'REST'
                              ? 'Worked · Rest day'
                              : record.day_type !== 'REG'
                                ? `${record.work_type} · ${record.day_type}`
                                : record.record_status}
                        </div>
                        {record.leave_applications.map((leave) => (
                          <div key={leave.application_no} className="mt-1">
                            <div className={`text-xs font-medium ${leave.status === 'APPROVED' ? 'text-emerald-700' : 'text-slate-600'}`}>
                              {leave.status === 'APPROVED' ? 'Approved leave' : `${leave.status} leave`}
                              {' · '}
                              {leave.leave_type}
                            </div>
                            <div className="text-xs text-slate-500">
                              Paid leave {formatHours(leave.paid_minutes)}
                              {' · '}
                              Unpaid leave {formatHours(leave.unpaid_minutes)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="line-clamp-2">
                        {record.worked_minutes != null && record.worked_minutes > 0 && (
                          <div className="whitespace-nowrap">{formatHours(record.worked_minutes)} worked</div>
                        )}
                        {(record.late_minutes > 0 || record.undertime_minutes > 0) && (
                          <div className="whitespace-nowrap text-xs">
                            {record.late_minutes > 0 && (
                              <span className="font-semibold text-rose-700">
                                Late {formatHours(record.late_minutes)}
                              </span>
                            )}
                            {record.late_minutes > 0 && record.undertime_minutes > 0 && ' · '}
                            {record.undertime_minutes > 0 && (
                              <span className="font-semibold text-rose-700">
                                Undertime {formatHours(record.undertime_minutes)}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="line-clamp-2 text-xs">
                        {(record.regular_overtime_minutes > 0
                          || record.night_differential_overtime_minutes > 0) && (
                          <div className="whitespace-nowrap">
                            {record.regular_overtime_minutes > 0 && (
                              <span className="font-semibold text-emerald-700">
                                Regular OT {formatHours(record.regular_overtime_minutes)}
                              </span>
                            )}
                            {record.regular_overtime_minutes > 0
                              && record.night_differential_overtime_minutes > 0
                              && ' · '}
                            {record.night_differential_overtime_minutes > 0 && (
                              <span className="font-semibold text-emerald-700">
                                ND OT {formatHours(record.night_differential_overtime_minutes)}
                              </span>
                            )}
                          </div>
                        )}
                        {(record.night_differential_minutes > 0 || approvedOvertimeMinutes(record) > 0) && (
                          <div className="whitespace-nowrap">
                            {record.night_differential_minutes > 0 && (
                              <span className="font-semibold text-emerald-700">
                                Night diff {formatHours(record.night_differential_minutes)}
                              </span>
                            )}
                            {record.night_differential_minutes > 0 && approvedOvertimeMinutes(record) > 0 && ' · '}
                            {approvedOvertimeMinutes(record) > 0 && (
                              <>
                                Approved OT{' '}
                                <span className="font-medium text-emerald-700">
                                  {formatHours(approvedOvertimeMinutes(record))}
                                </span>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </td>
                    <td
                      className="break-words px-4 py-3"
                      title={[
                        ...record.leave_applications.map(
                          (leave) => `${leave.leave_type} · ${leave.status} · paid ${formatHours(leave.paid_minutes)} · unpaid ${formatHours(leave.unpaid_minutes)}`,
                        ),
                        ...record.overtime_applications.map(
                          (overtime) => `Overtime · ${overtime.status} · approved ${formatHours(overtime.approved_minutes)} · payable ${formatHours(overtime.payable_minutes)}`,
                        ),
                        ...record.official_business_requests.map(
                          (business) => `Official business · ${business.status} · approved ${formatHours(business.approved_minutes)} · credited ${formatHours(business.credited_minutes)} · ${formatTime(business.start_at)}–${formatTime(business.end_at)}`,
                        ),
                      ].join('\n')}
                    >
                      <div className="line-clamp-2">
                        {record.leave_applications.length
                          ? record.leave_applications.map((leave) => (
                            <div key={leave.application_no}>
                              <div>
                                <span className="font-medium">{leave.leave_type}</span> · {leave.status}
                              </div>
                              <div className="text-xs text-slate-500">
                                Paid {formatHours(leave.paid_minutes)} · Unpaid {formatHours(leave.unpaid_minutes)}
                              </div>
                            </div>
                          ))
                          : '—'}
                        {record.overtime_applications.length
                          ? record.overtime_applications.map((overtime) => (
                            <div key={overtime.application_no}>
                              <div>
                                <span className="font-medium">Overtime</span> · {overtime.status}
                              </div>
                              <div className="text-xs text-slate-500">
                                Approved {formatHours(overtime.approved_minutes)} · Payable {formatHours(overtime.payable_minutes)}
                              </div>
                            </div>
                          ))
                          : null}
                        {record.official_business_requests.length
                          ? record.official_business_requests.map((business) => (
                            <div key={business.request_no}>
                              <div>
                                <span className="font-medium">Official business</span> · {business.status}
                              </div>
                              <div className="text-xs text-slate-500">
                                Approved {formatHours(business.approved_minutes)} · Credited {formatHours(business.credited_minutes)} · {formatTime(business.start_at)}–{formatTime(business.end_at)}
                              </div>
                            </div>
                          ))
                          : null}
                        {!record.leave_applications.length
                          && !record.overtime_applications.length
                          && !record.official_business_requests.length
                          && '—'}
                      </div>
                    </td>
                      </tr>
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          {records.length} record{records.length === 1 ? '' : 's'} · Reports support up to 31 days per search.
        </p>
      </main>
    </div>
  )
}

export default AttendanceDetailReport
