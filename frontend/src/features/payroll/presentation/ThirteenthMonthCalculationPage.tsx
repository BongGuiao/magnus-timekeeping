import { useState, type FormEvent } from 'react'
import TopNav, { type NavView } from '../../../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../../../hooks/useCompanySetupSelection'
import type { ThirteenthMonthRun } from '../domain/payroll'
import type { PayrollUseCases } from '../application/useCases'

interface Props {
  employeeName: string
  useCases: PayrollUseCases
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

function amount(value: number): string {
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function ThirteenthMonthCalculationPage({
  employeeName,
  useCases,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { companyId } = useCompanySetupSelection()
  const [taxYear, setTaxYear] = useState(String(new Date().getFullYear()))
  const [coveredPeriodFrom, setCoveredPeriodFrom] = useState('')
  const [coveredPeriodTo, setCoveredPeriodTo] = useState('')
  const [calculating, setCalculating] = useState(false)
  const [run, setRun] = useState<ThirteenthMonthRun | null>(null)
  const [error, setError] = useState('')

  async function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!companyId) return
    setCalculating(true)
    setRun(null)
    setError('')
    try {
      const result = await useCases.calculateThirteenthMonth(
        companyId,
        Number(taxYear),
        coveredPeriodFrom,
        coveredPeriodTo,
      )
      setRun(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not calculate 13th-month pay.')
    } finally {
      setCalculating(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView="payroll-thirteenth-month"
        onNavigate={onNavigate}
        onSignOut={onLoggedOut}
      />
      <main className="mx-auto w-[95%] max-w-7xl space-y-5 py-6">
        <header>
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Payroll</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">13th-Month Calculation</h1>
          <p className="mt-1 max-w-4xl text-sm text-slate-600">
            Calculate statutory 13th-month pay from eligible basic salary and paid-leave earnings.
            Choose the date range of the last payroll cutoff to include for this tax year.
          </p>
        </header>

        {error && (
          <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </p>
        )}

        {!companyId && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Select your assigned company from the company selector above to calculate 13th-month pay.
          </p>
        )}
        {companyId && (
          <section className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Calculate 13th-month pay</h2>
              <p className="mt-1 max-w-4xl text-sm text-slate-600">
                Regular pay and paid-leave pay are included; benefits, overtime, night differential,
                and reimbursements are excluded. Lates, undertime, and unpaid absences reduce the
                amount only when they already reduced recorded basic earnings.
              </p>
              <p className="mt-1 text-xs text-slate-500">
                This creates or replaces the current calculation run for the selected year. It uses
                current READY payroll results through the selected cutoff; calculate eligible
                payroll results before running this calculation. The run does not post payment.
              </p>
            </div>

            <form onSubmit={(event) => void calculate(event)} className="flex flex-wrap items-end gap-3">
              <label className="text-xs font-semibold text-slate-600">
                Tax year
                <input
                  type="number"
                  min="1900"
                  max="9999"
                  required
                  value={taxYear}
                  onChange={(event) => {
                    setTaxYear(event.target.value)
                    setCoveredPeriodFrom('')
                    setCoveredPeriodTo('')
                  }}
                  className="mt-1 block w-32 rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900"
                />
              </label>
              <label className="text-xs font-semibold text-slate-600">
                Last cutoff from
                <input
                  type="date"
                  required
                  min={`${taxYear}-01-01`}
                  max={`${taxYear}-12-31`}
                  value={coveredPeriodFrom}
                  onChange={(event) => setCoveredPeriodFrom(event.target.value)}
                  className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900"
                />
              </label>
              <label className="text-xs font-semibold text-slate-600">
                Last cutoff to
                <input
                  type="date"
                  required
                  min={`${taxYear}-01-01`}
                  max={`${taxYear}-12-31`}
                  value={coveredPeriodTo}
                  onChange={(event) => setCoveredPeriodTo(event.target.value)}
                  className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900"
                />
              </label>
              <button
                type="submit"
                disabled={!companyId || calculating || !coveredPeriodFrom || !coveredPeriodTo}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {calculating ? 'Calculating…' : 'Calculate'}
              </button>
            </form>

            <p className="text-xs text-slate-500">
              Enter the From and To dates of the last payroll cutoff to include. The To date must
              match an active cutoff for this company. Choose a November cutoff when the company
              releases 13th-month pay by December 15, or a December cutoff when December earnings
              should be included.
            </p>

            {run && (
              <div className="overflow-x-auto">
                <p role="status" className="mb-3 text-sm font-semibold text-emerald-700">
                  Tax year {run.taxYear}, payroll cutoff {run.coveredPeriodFrom} – {run.coveredPeriodTo}:
                  {' '}calculated for {run.results.length} employee(s).
                </p>
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th scope="col" className="px-3 py-2">Employee</th>
                      <th scope="col" className="px-3 py-2 text-right">Basic earned</th>
                      <th scope="col" className="px-3 py-2 text-right">13th month</th>
                      <th scope="col" className="px-3 py-2 text-right">Tax exempt</th>
                      <th scope="col" className="px-3 py-2 text-right">Taxable</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {run.results.map((result) => (
                      <tr key={result.employeeId}>
                        <th scope="row" className="px-3 py-2 text-left font-medium text-slate-800">
                          {result.employeeName} <span className="text-xs text-slate-500">({result.employeeNo})</span>
                        </th>
                        <td className="px-3 py-2 text-right">{amount(result.basicSalaryEarned)}</td>
                        <td className="px-3 py-2 text-right">{amount(result.thirteenthMonthPay)}</td>
                        <td className="px-3 py-2 text-right">{amount(result.taxExemptAmount)}</td>
                        <td className="px-3 py-2 text-right">{amount(result.taxableAmount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  )
}
