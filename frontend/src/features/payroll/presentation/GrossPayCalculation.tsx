import { useEffect, useMemo, useState } from 'react'
import { Calculator, RefreshCw } from 'lucide-react'
import type { PayrollUseCases } from '../application/useCases'
import type { GrossPayRun, PayrollCutoffOption, PayrollEmployeeOption } from '../domain/payroll'
import { payrollComponentLabels } from '../domain/payroll'

interface Props {
  payrollGroupLabel: string
  cutoffs: PayrollCutoffOption[]
  selectedCutoffId: string
  onSelectCutoff: (cutoffId: string) => void
  onCutoffLockChanged: (cutoffId: string, locked: boolean) => void
  employees: PayrollEmployeeOption[]
  useCases: PayrollUseCases
  canApprovePayroll: boolean
  canUnlockPayroll: boolean
}

const selectClass = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function formatCurrency(amount: number, currency: string | null) {
  if (!currency) return '—'
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(amount)
}

function formatHours(minutes: number) {
  return `${(minutes / 60).toLocaleString(undefined, { maximumFractionDigits: 2 })} hr`
}

function contributionName(programCode: string) {
  switch (programCode) {
    case 'SSS':
      return 'SSS'
    case 'PHILHEALTH':
      return 'PhilHealth'
    case 'PAGIBIG':
      return 'Pag-IBIG'
    default:
      return programCode
  }
}

export default function GrossPayCalculation({
  payrollGroupLabel,
  cutoffs,
  selectedCutoffId,
  onSelectCutoff,
  onCutoffLockChanged,
  employees,
  useCases,
  canApprovePayroll,
  canUnlockPayroll,
}: Props) {
  const [run, setRun] = useState<GrossPayRun | null>(null)
  const [loading, setLoading] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [finalizationAction, setFinalizationAction] = useState<'approve' | 'unlock' | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let current = true
    setRun(null)
    setError('')
    if (!selectedCutoffId) return () => { current = false }
    setLoading(true)
    useCases.getCurrentGrossPayRun(selectedCutoffId)
      .then((result) => {
        if (current) setRun(result)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load gross-pay results.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [selectedCutoffId, useCases])

  const employeeById = useMemo(() => new Map(employees.map((employee) => [employee.id, employee])), [employees])
  const readyCount = run?.results.filter((result) => result.status === 'READY').length ?? 0
  const holdCount = (run?.results.length ?? 0) - readyCount
  const selectedCutoff = cutoffs.find((cutoff) => cutoff.id === selectedCutoffId)
  const canFinalize = Boolean(run && run.results.length > 0 && holdCount === 0)
  const attendanceFinalized = Boolean(selectedCutoff?.attendanceFinalized)

  async function calculate() {
    setError('')
    setNotice('')
    setCalculating(true)
    try {
      setRun(await useCases.calculateGrossPay(selectedCutoffId))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not calculate gross pay.')
    } finally {
      setCalculating(false)
    }
  }

  async function approvePayroll() {
    const cutoffLabel = selectedCutoff?.code ?? 'this cutoff'
    if (!window.confirm(`Approve and lock payroll for ${cutoffLabel}? It cannot be recalculated unless an administrator unlocks it.`)) return
    setError('')
    setNotice('')
    setFinalizationAction('approve')
    try {
      await useCases.approvePayrollCutoff(selectedCutoffId)
      onCutoffLockChanged(selectedCutoffId, true)
      setNotice(`Payroll for ${cutoffLabel} was approved and locked.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not approve payroll.')
    } finally {
      setFinalizationAction(null)
    }
  }

  async function unlockPayroll() {
    const cutoffLabel = selectedCutoff?.code ?? 'this cutoff'
    if (!window.confirm(`Unlock payroll for ${cutoffLabel}? An administrator can then make corrections and recalculate.`)) return
    setError('')
    setNotice('')
    setFinalizationAction('unlock')
    try {
      await useCases.unlockPayrollCutoff(selectedCutoffId)
      onCutoffLockChanged(selectedCutoffId, false)
      setNotice(`Payroll for ${cutoffLabel} was unlocked for correction.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not unlock payroll.')
    } finally {
      setFinalizationAction(null)
    }
  }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Payroll processing</p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-64 flex-1">
            <h2 className="text-xl font-bold text-slate-900">Payroll calculation</h2>
            <p className="mt-1 text-sm text-slate-500">{payrollGroupLabel}. Calculate, review, and finalize gross-to-net payroll for a cutoff.</p>
            <label className="mt-4 block max-w-xl text-xs font-bold uppercase tracking-wide text-slate-500">
              Payroll cutoff
              <select className={`${selectClass} mt-1 normal-case`} value={selectedCutoffId} onChange={(event) => onSelectCutoff(event.target.value)}>
                <option value="">Select a cutoff</option>
                {cutoffs.map((cutoff) => (
                  <option key={cutoff.id} value={cutoff.id}>
                    {cutoff.code} · {cutoff.periodStart} to {cutoff.periodEnd}
                    {cutoff.locked ? ' · PAYROLL LOCKED' : cutoff.attendanceFinalized ? ' · ATTENDANCE FINALIZED' : ' · ATTENDANCE OPEN'}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="button"
            onClick={() => void calculate()}
            disabled={
              !selectedCutoffId
              || Boolean(selectedCutoff?.locked)
              || !attendanceFinalized
              || calculating
              || loading
            }
            title={!attendanceFinalized ? 'Finalize attendance in Attendance Detail before calculating payroll.' : undefined}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {run ? <RefreshCw className="h-4 w-4" /> : <Calculator className="h-4 w-4" />}
            {calculating ? 'Calculating…' : run ? 'Recalculate payroll' : 'Calculate payroll'}
          </button>
          {selectedCutoff?.locked ? (
            <div className="flex items-center gap-2">
              <span className="rounded-lg bg-emerald-50 px-3 py-2.5 text-sm font-semibold text-emerald-800">
                Payroll approved and locked
              </span>
              {canUnlockPayroll && (
                <button
                  type="button"
                  onClick={() => void unlockPayroll()}
                  disabled={finalizationAction !== null || calculating}
                  className="rounded-lg border border-amber-300 px-3 py-2.5 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                >
                  {finalizationAction === 'unlock' ? 'Unlocking…' : 'Unlock for correction'}
                </button>
              )}
            </div>
          ) : canApprovePayroll && (
            <button
              type="button"
              onClick={() => void approvePayroll()}
              disabled={!canFinalize || finalizationAction !== null || calculating || loading}
              title={!canFinalize ? 'Calculate payroll and resolve all HOLD results before approval.' : undefined}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {finalizationAction === 'approve' ? 'Approving…' : 'Approve and lock payroll'}
            </button>
          )}
        </div>
        <p className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900">
          Finalize attendance in Attendance Detail before calculating payroll. After attendance is finalized, the calculation uses the saved cutoff results and does not recalculate attendance.
        </p>
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Net pay remains on HOLD until effective statutory schedules and any required employee tax-year opening balances are available. Missing compensation, earning rules, or approved worked minutes also keeps results on HOLD. Only a separate HR administrator can approve and lock payroll after attendance is finalized and the attendance deadline has passed. Employer contributions are reported separately and are not deducted from employee pay.
        </p>
        {notice && <p role="status" className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
        {error && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      </section>

      {loading && <p role="status" className="rounded-xl border border-slate-200 bg-white px-5 py-6 text-sm text-slate-500">Loading saved payroll results…</p>}
      {!loading && selectedCutoffId && !run && !error && (
        <p className="rounded-xl border border-slate-200 bg-white px-5 py-6 text-sm text-slate-500">No payroll calculation has been saved for this cutoff.</p>
      )}

      {!loading && run && (
        <>
          <section className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Employees</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">{run.results.length}</p>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">Ready</p>
              <p className="mt-2 text-2xl font-bold text-emerald-900">{readyCount}</p>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-xs font-bold uppercase tracking-wide text-amber-800">On hold</p>
              <p className="mt-2 text-2xl font-bold text-amber-950">{holdCount}</p>
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div>
                <h3 className="font-bold text-slate-900">Payroll results · {selectedCutoff?.code ?? run.cutoffId}</h3>
                <p className="mt-1 text-xs text-slate-500">
                  {selectedCutoff ? `${selectedCutoff.periodStart} → ${selectedCutoff.periodEnd}` : run.calculationVersion}
                  {' · '}Calculated {new Date(run.calculatedAt).toLocaleString()}
                </p>
              </div>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600">{run.calculationVersion}</span>
            </div>
            {run.results.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-500">This cutoff has no employee time results.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-[1120px] w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-5 py-3">Employee</th>
                      <th className="px-5 py-3">Base rate</th>
                      <th className="px-5 py-3">Gross pay</th>
                      <th className="px-5 py-3">Cash benefits</th>
                      <th className="px-5 py-3">Total deductions</th>
                      <th className="px-5 py-3">Net pay</th>
                      <th className="px-5 py-3">Status</th>
                      <th className="px-5 py-3">Calculation details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {run.results.map((result) => {
                      const employee = employeeById.get(result.employeeId)
                      const limitedBenefitTotal = result.benefitLines.reduce((total, line) => (
                        line.category !== 'EMPLOYEE_DEDUCTION' && line.taxTreatment === 'EXEMPT_LIMITED'
                          ? total + line.amount
                          : total
                      ), 0)
                      const taxableBenefitsAdded = result.benefitLines.reduce((total, line) => (
                        line.category !== 'EMPLOYEE_DEDUCTION' && line.taxTreatment === 'TAXABLE'
                          ? total + line.amount
                          : total
                      ), 0) + Math.max(0, limitedBenefitTotal - (result.exemptLimitedBenefitAmount ?? 0))
                      return (
                        <tr key={result.cutoffResultId} className="align-top">
                          <td className="whitespace-nowrap px-5 py-4">
                            <p className="font-semibold text-slate-900">{employee?.fullName ?? 'Employee record'}</p>
                            <p className="mt-0.5 text-xs text-slate-500">{employee?.employeeNo ?? result.employeeId}</p>
                          </td>
                          <td className="whitespace-nowrap px-5 py-4">{formatCurrency(result.baseRate ?? 0, result.currency)}</td>
                          <td className="whitespace-nowrap px-5 py-4 font-bold text-slate-900">{formatCurrency(result.grossAmount ?? 0, result.currency)}</td>
                          <td className="whitespace-nowrap px-5 py-4">{formatCurrency(result.cashBenefitAmount, result.currency)}</td>
                          <td className="whitespace-nowrap px-5 py-4">
                            {result.employeeContributions === null || result.withholdingTax === null
                              ? '—'
                              : formatCurrency(
                                result.employeeContributions + result.withholdingTax + result.employeeBenefitDeductions,
                                result.currency,
                              )}
                          </td>
                          <td className="whitespace-nowrap px-5 py-4 font-bold text-slate-900">
                            {result.netAmount === null ? '—' : formatCurrency(result.netAmount, result.currency)}
                          </td>
                          <td className="px-5 py-4">
                            <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${result.status === 'READY' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>
                              {result.status}
                            </span>
                            {result.grossStatus !== result.status && (
                              <p className="mt-2 text-xs font-semibold text-slate-600">Gross pay: {result.grossStatus}</p>
                            )}
                            {result.holdReason && <p className="mt-2 max-w-64 text-xs leading-5 text-amber-900">{result.holdReason}</p>}
                          </td>
                          <td className="px-5 py-4">
                            {result.lines.length === 0 ? (
                              <span className="text-xs text-slate-400">No amounts calculated</span>
                            ) : (
                              <details className="max-w-lg">
                                <summary className="cursor-pointer text-xs font-semibold text-indigo-700">View pay breakdown</summary>
                                <div className="mt-3 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                                  <section>
                                    <h4 className="font-bold text-slate-800">1. Gross pay build-up</h4>
                                    <p className="mt-1 text-slate-500">
                                      Gross pay is the sum of these pay components. A negative unpaid-time line reduces gross pay; statutory deductions are not part of gross pay.
                                    </p>
                                    <ul className="mt-2 space-y-2">
                                      {result.lines
                                        .filter((line) => line.minutes > 0 || line.amount !== 0)
                                        .map((line) => {
                                          const description = line.componentCode === 'MONTHLY_BASE'
                                            ? 'Monthly salary allocated to this cutoff'
                                            : line.componentCode === 'UNPAID_TIME_DEDUCTION'
                                              ? `${formatHours(line.minutes)} unpaid scheduled time`
                                              : `${formatHours(line.minutes)} × ${line.multiplier.toLocaleString(undefined, { maximumFractionDigits: 3 })} multiplier`
                                          const label = line.componentCode === 'MONTHLY_BASE'
                                            ? 'Monthly base salary'
                                            : line.componentCode === 'UNPAID_TIME_DEDUCTION'
                                              ? 'Unpaid-time deduction'
                                              : payrollComponentLabels[line.componentCode]
                                          return (
                                            <li key={line.componentCode} className="flex justify-between gap-4">
                                              <span>
                                                <span className="block font-medium text-slate-700">{label}</span>
                                                <span className="block text-slate-500">{description}</span>
                                              </span>
                                              <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(line.amount, result.currency)}</span>
                                            </li>
                                          )
                                        })}
                                      {!result.lines.some((line) => line.minutes > 0 || line.amount !== 0) && (
                                        <li className="text-slate-500">No payable time components.</li>
                                      )}
                                      <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-bold text-slate-900">
                                        <span>Gross pay</span>
                                        <span>{formatCurrency(result.grossAmount ?? 0, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  <section>
                                    <h4 className="font-bold text-slate-800">2. Cash benefits added</h4>
                                    <ul className="mt-2 space-y-1.5">
                                      {result.benefitLines
                                        .filter((line) => ['CASH_ALLOWANCE', 'ONE_TIME_BONUS', 'REIMBURSEMENT'].includes(line.category))
                                        .map((line, index) => (
                                          <li key={`${line.benefitCode}-${index}`} className="flex justify-between gap-4">
                                            <span className="text-slate-700">{line.benefitName}</span>
                                            <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(line.amount, result.currency)}</span>
                                          </li>
                                        ))}
                                      {result.benefitLines.every((line) => !['CASH_ALLOWANCE', 'ONE_TIME_BONUS', 'REIMBURSEMENT'].includes(line.category)) && (
                                        <li className="text-slate-500">No cash benefits for this cutoff.</li>
                                      )}
                                      <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-semibold text-slate-800">
                                        <span>Total cash benefits</span>
                                        <span>{formatCurrency(result.cashBenefitAmount, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  <section>
                                    <h4 className="font-bold text-slate-800">3. Employee statutory contributions</h4>
                                    <p className="mt-1 text-slate-500">
                                      These are the employee shares withheld from pay. The employer shares below are separate and are not deducted from net pay.
                                    </p>
                                    <ul className="mt-2 space-y-1.5">
                                      {result.contributionLines.map((line) => (
                                        <li key={line.programCode} className="flex justify-between gap-4">
                                          <span className="text-slate-700">{contributionName(line.programCode)}</span>
                                          <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(line.employeeAmount, result.currency)}</span>
                                        </li>
                                      ))}
                                      {result.contributionLines.length === 0 && (
                                        <li className="text-slate-500">Contribution details are unavailable.</li>
                                      )}
                                      <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-semibold text-slate-800">
                                        <span>Total employee contributions</span>
                                        <span>{result.employeeContributions === null ? '—' : formatCurrency(result.employeeContributions, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  <section>
                                    <h4 className="font-bold text-slate-800">4. Taxable income and withholding tax</h4>
                                    <p className="mt-1 text-slate-500">
                                      Taxable income reflects gross pay plus taxable benefits, less employee statutory contributions. Tax-exempt benefits are excluded; limited-exemption benefits may be taxable above their remaining limit. WTAX uses the configured schedule and may apply year-to-date or year-end reconciliation rules.
                                    </p>
                                    <ul className="mt-2 space-y-1.5">
                                      <li className="flex justify-between gap-4">
                                        <span className="text-slate-700">Gross pay</span>
                                        <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(result.grossAmount ?? 0, result.currency)}</span>
                                      </li>
                                      <li className="flex justify-between gap-4">
                                        <span className="text-slate-700">+ Taxable benefits</span>
                                        <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(taxableBenefitsAdded, result.currency)}</span>
                                      </li>
                                      <li className="flex justify-between gap-4">
                                        <span className="text-slate-700">− Employee statutory contributions</span>
                                        <span className="whitespace-nowrap font-medium text-slate-800">{result.employeeContributions === null ? '—' : formatCurrency(result.employeeContributions, result.currency)}</span>
                                      </li>
                                      <li className="flex justify-between gap-4">
                                        <span className="font-semibold text-slate-800">= Taxable income this cutoff</span>
                                        <span className="whitespace-nowrap font-medium text-slate-800">{result.taxableIncome === null ? '—' : formatCurrency(result.taxableIncome, result.currency)}</span>
                                      </li>
                                      <li className="flex justify-between gap-4">
                                        <span className="text-slate-700">Withholding tax (WTAX)</span>
                                        <span className="whitespace-nowrap font-medium text-slate-800">{result.withholdingTax === null ? '—' : formatCurrency(result.withholdingTax, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  <section>
                                    <h4 className="font-bold text-slate-800">5. Other employee benefit deductions</h4>
                                    <p className="mt-1 text-slate-500">
                                      Non-statutory deductions such as loans or cash advances, deducted from net pay separately from statutory contributions and WTAX.
                                    </p>
                                    <ul className="mt-2 space-y-1.5">
                                      {result.benefitLines
                                        .filter((line) => line.category === 'EMPLOYEE_DEDUCTION')
                                        .map((line, index) => (
                                          <li key={`${line.benefitCode}-${index}`} className="flex justify-between gap-4">
                                            <span className="text-slate-700">{line.benefitName}</span>
                                            <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(line.amount, result.currency)}</span>
                                          </li>
                                        ))}
                                      {result.benefitLines.every((line) => line.category !== 'EMPLOYEE_DEDUCTION') && (
                                        <li className="text-slate-500">No other employee benefit deductions.</li>
                                      )}
                                      <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-semibold text-slate-800">
                                        <span>Total employee benefit deductions</span>
                                        <span>{formatCurrency(result.employeeBenefitDeductions, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  <section>
                                    <h4 className="font-bold text-slate-800">6. Net pay reconciliation</h4>
                                    <ul className="mt-2 space-y-1.5">
                                      <li className="flex justify-between gap-4"><span>Gross pay</span><span>{formatCurrency(result.grossAmount ?? 0, result.currency)}</span></li>
                                      <li className="flex justify-between gap-4"><span>+ Cash benefits</span><span>{formatCurrency(result.cashBenefitAmount, result.currency)}</span></li>
                                      <li className="flex justify-between gap-4"><span>− Employee statutory contributions</span><span>{result.employeeContributions === null ? '—' : formatCurrency(result.employeeContributions, result.currency)}</span></li>
                                      <li className="flex justify-between gap-4"><span>− Withholding tax</span><span>{result.withholdingTax === null ? '—' : formatCurrency(result.withholdingTax, result.currency)}</span></li>
                                      <li className="flex justify-between gap-4"><span>− Other employee benefit deductions</span><span>{formatCurrency(result.employeeBenefitDeductions, result.currency)}</span></li>
                                      <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-bold text-slate-900">
                                        <span>Net pay</span>
                                        <span>{result.netAmount === null ? '—' : formatCurrency(result.netAmount, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  <section className="border-t border-slate-200 pt-3">
                                    <h4 className="font-bold text-slate-700">Employer contributions (not deducted from employee pay)</h4>
                                    <ul className="mt-2 space-y-1.5">
                                      {result.contributionLines.map((line) => (
                                        <li key={line.programCode} className="flex justify-between gap-4">
                                          <span className="text-slate-600">{contributionName(line.programCode)}</span>
                                          <span className="whitespace-nowrap text-slate-700">{formatCurrency(line.employerAmount, result.currency)}</span>
                                        </li>
                                      ))}
                                      <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-semibold text-slate-700">
                                        <span>Total employer contributions</span>
                                        <span>{result.employerContributions === null ? '—' : formatCurrency(result.employerContributions, result.currency)}</span>
                                      </li>
                                    </ul>
                                  </section>

                                  {result.benefitLines.some((line) => ['EMPLOYER_PAID_INSURANCE', 'NON_CASH'].includes(line.category)) && (
                                    <section className="border-t border-slate-200 pt-3">
                                      <h4 className="font-bold text-slate-700">Non-cash benefits (not part of cash net pay)</h4>
                                      <ul className="mt-2 space-y-1.5">
                                        {result.benefitLines
                                          .filter((line) => ['EMPLOYER_PAID_INSURANCE', 'NON_CASH'].includes(line.category))
                                          .map((line, index) => (
                                            <li key={`${line.benefitCode}-${index}`} className="flex justify-between gap-4">
                                              <span className="text-slate-600">{line.benefitName}</span>
                                              <span className="whitespace-nowrap text-slate-700">{formatCurrency(line.amount, result.currency)}</span>
                                            </li>
                                          ))}
                                        <li className="flex justify-between gap-4 border-t border-slate-200 pt-2 font-semibold text-slate-700">
                                          <span>Total non-cash benefits</span>
                                          <span>{formatCurrency(result.nonCashBenefitAmount, result.currency)}</span>
                                        </li>
                                      </ul>
                                    </section>
                                  )}
                                </div>
                              </details>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
