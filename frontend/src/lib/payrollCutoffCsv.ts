import type { EmployeeCutoffResult, PayrollCutoff } from './payrollCutoffApi'

const HEADERS = [
  'Cutoff code',
  'Payroll group',
  'Period start',
  'Period end',
  'Employee ID',
  'Employee',
  'Scheduled days',
  'Paid days',
  'Regular (hours)',
  'Late (hours)',
  'Undertime (hours)',
  'Absence (hours)',
  'Paid leave (hours)',
  'Unpaid leave (hours)',
  'Ordinary OT (hours)',
  'Rest day (hours)',
  'Rest day OT (hours)',
  'Special day (hours)',
  'Special day OT (hours)',
  'Holiday (hours)',
  'Holiday OT (hours)',
  'Night regular (hours)',
  'Night OT (hours)',
  'Official business (hours)',
  'Exceptions',
  'Payroll status',
]

function csvCell(value: string, header: string): string {
  if (/^[=+\-@]/.test(value.trimStart())) {
    throw new Error(`Cannot export ${header}: its value could be interpreted as a spreadsheet formula.`)
  }
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value
}

function hours(minutes: number): string {
  return (minutes / 60).toFixed(2)
}

export function payrollCutoffResultsCsv(
  cutoff: Pick<PayrollCutoff, 'cutoff_code' | 'period_start' | 'period_end'>,
  payrollGroup: string,
  results: EmployeeCutoffResult[],
): string {
  const rows = [
    HEADERS,
    ...results.map((result) => [
      cutoff.cutoff_code,
      payrollGroup,
      cutoff.period_start,
      cutoff.period_end,
      result.employee_id,
      result.employee_name ?? '',
      String(result.scheduled_days),
      String(result.paid_days),
      hours(result.regular_minutes),
      hours(result.late_minutes),
      hours(result.undertime_minutes),
      hours(result.absence_minutes),
      hours(result.paid_leave_minutes),
      hours(result.unpaid_leave_minutes),
      hours(result.ordinary_ot_minutes),
      hours(result.rest_day_minutes),
      hours(result.rest_day_ot_minutes),
      hours(result.special_day_minutes),
      hours(result.special_day_ot_minutes),
      hours(result.holiday_minutes),
      hours(result.holiday_ot_minutes),
      hours(result.night_regular_minutes),
      hours(result.night_ot_minutes),
      hours(result.official_business_minutes),
      String(result.exception_count),
      result.payroll_status,
    ]),
  ]

  const contents = rows
    .map((row) => row.map((value, index) => csvCell(value, HEADERS[index] ?? 'value')).join(','))
    .join('\r\n')
  return `\uFEFF${contents}\r\n`
}

export function payrollCutoffResultsFilename(cutoffCode: string, periodStart: string, periodEnd: string): string {
  const safeCutoffCode = cutoffCode.trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  return `${safeCutoffCode || 'payroll-cutoff'}-time-results-${periodStart.slice(0, 10)}-${periodEnd.slice(0, 10)}.csv`
}
