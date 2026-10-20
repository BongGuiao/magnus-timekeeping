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
  employees: PayrollEmployeeOption[]
  useCases: PayrollUseCases
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

export default function GrossPayCalculation({
  payrollGroupLabel,
  cutoffs,
  selectedCutoffId,
  onSelectCutoff,
  employees,
  useCases,
}: Props) {
  const [run, setRun] = useState<GrossPayRun | null>(null)
  const [loading, setLoading] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [error, setError] = useState('')

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

  async function calculate() {
    setError('')
    setCalculating(true)
    try {
      setRun(await useCases.calculateGrossPay(selectedCutoffId))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not calculate gross pay.')
    } finally {
      setCalculating(false)
    }
  }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Payroll processing</p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-64 flex-1">
            <h2 className="text-xl font-bold text-slate-900">Payroll calculation</h2>
            <p className="mt-1 text-sm text-slate-500">{payrollGroupLabel}. Select an open cutoff to calculate benefits, statutory deductions, and net pay.</p>
            <label className="mt-4 block max-w-xl text-xs font-bold uppercase tracking-wide text-slate-500">
              Payroll cutoff
              <select className={`${selectClass} mt-1 normal-case`} value={selectedCutoffId} onChange={(event) => onSelectCutoff(event.target.value)}>
                <option value="">Select a cutoff</option>
                {cutoffs.map((cutoff) => (
                  <option key={cutoff.id} value={cutoff.id} disabled={cutoff.locked}>
                    {cutoff.code} · {cutoff.periodStart} to {cutoff.periodEnd}{cutoff.locked ? ' · LOCKED' : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="button"
            onClick={() => void calculate()}
            disabled={!selectedCutoffId || Boolean(selectedCutoff?.locked) || calculating || loading}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {run ? <RefreshCw className="h-4 w-4" /> : <Calculator className="h-4 w-4" />}
            {calculating ? 'Calculating…' : run ? 'Recalculate payroll' : 'Calculate payroll'}
          </button>
        </div>
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Net pay remains on HOLD until effective statutory schedules and the employee tax-year opening balances are available. Missing compensation, earning rules, approved worked minutes, or required acknowledgments also keeps results on HOLD. Employer contributions are reported separately and are not deducted from employee pay.
        </p>
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
                      <th className="px-5 py-3">Gross amount</th>
                      <th className="px-5 py-3">Cash benefits</th>
                      <th className="px-5 py-3">Employee deductions</th>
                      <th className="px-5 py-3">Net pay</th>
                      <th className="px-5 py-3">Status</th>
                      <th className="px-5 py-3">Calculation details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {run.results.map((result) => {
                      const employee = employeeById.get(result.employeeId)
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
                              <details className="max-w-sm">
                                <summary className="cursor-pointer text-xs font-semibold text-indigo-700">View pay breakdown</summary>
                                <ul className="mt-2 space-y-1.5 text-xs text-slate-600">
                                  {result.lines.filter((line) => line.minutes > 0).map((line) => (
                                    <li key={line.componentCode} className="flex justify-between gap-4">
                                      <span>{payrollComponentLabels[line.componentCode]} · {formatHours(line.minutes)}</span>
                                      <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(line.amount, result.currency)}</span>
                                    </li>
                                  ))}
                                  {!result.lines.some((line) => line.minutes > 0) && <li>No payable time components.</li>}
                                  {result.benefitLines.map((line, index) => (
                                    <li key={`${line.benefitCode}-${index}`} className="flex justify-between gap-4">
                                      <span>{line.benefitName} · {line.taxTreatment.toLowerCase().replace('_', ' ')}</span>
                                      <span className="whitespace-nowrap font-medium text-slate-800">{formatCurrency(line.amount, result.currency)}</span>
                                    </li>
                                  ))}
                                  {result.employeeContributions !== null && <li className="flex justify-between gap-4 border-t border-slate-100 pt-1"><span>Employee statutory contributions</span><span>{formatCurrency(result.employeeContributions, result.currency)}</span></li>}
                                  {result.withholdingTax !== null && <li className="flex justify-between gap-4"><span>Withholding tax</span><span>{formatCurrency(result.withholdingTax, result.currency)}</span></li>}
                                  {result.employeeBenefitDeductions > 0 && <li className="flex justify-between gap-4"><span>Employee benefit deductions</span><span>{formatCurrency(result.employeeBenefitDeductions, result.currency)}</span></li>}
                                  {result.employerContributions !== null && <li className="flex justify-between gap-4 border-t border-slate-100 pt-1 font-semibold text-slate-700"><span>Employer contributions (not deducted)</span><span>{formatCurrency(result.employerContributions, result.currency)}</span></li>}
                                </ul>
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
