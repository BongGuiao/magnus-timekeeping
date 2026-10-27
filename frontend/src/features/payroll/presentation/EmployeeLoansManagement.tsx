import { useState, type FormEvent } from 'react'
import { Landmark, Plus, X } from 'lucide-react'
import type { PayrollUseCases } from '../application/useCases'
import type {
  EmployeeLoan,
  EmployeeLoanSchedule,
  PayrollEmployeeOption,
} from '../domain/payroll'

interface Props {
  payrollGroupId: string
  employees: PayrollEmployeeOption[]
  loans: EmployeeLoan[]
  useCases: PayrollUseCases
  onLoansChanged: (loans: EmployeeLoan[]) => void
}

const schedules: { value: EmployeeLoanSchedule; label: string }[] = [
  { value: 'FIRST_HALF', label: 'First cutoff' },
  { value: 'SECOND_HALF', label: 'Second cutoff' },
  { value: 'EVERY_CUTOFF', label: 'Both cutoffs' },
]

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

const today = new Date().toISOString().slice(0, 10)

function formatMoney(value: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'PHP' }).format(value)
}

export default function EmployeeLoansManagement({
  payrollGroupId,
  employees,
  loans,
  useCases,
  onLoansChanged,
}: Props) {
  const [employeeId, setEmployeeId] = useState('')
  const [employeeSearch, setEmployeeSearch] = useState('')
  const [isEmployeeListOpen, setIsEmployeeListOpen] = useState(false)
  const [referenceNumber, setReferenceNumber] = useState('')
  const [principal, setPrincipal] = useState('')
  const [installment, setInstallment] = useState('')
  const [schedule, setSchedule] = useState<EmployeeLoanSchedule>('EVERY_CUTOFF')
  const [effectiveFrom, setEffectiveFrom] = useState(today)
  const [restructuringLoan, setRestructuringLoan] = useState<EmployeeLoan | null>(null)
  const [additionalPrincipal, setAdditionalPrincipal] = useState('0')
  const [restructureReference, setRestructureReference] = useState('')
  const [restructureInstallment, setRestructureInstallment] = useState('')
  const [restructureSchedule, setRestructureSchedule] = useState<EmployeeLoanSchedule>('EVERY_CUTOFF')
  const [restructureDate, setRestructureDate] = useState(today)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const selectedEmployee = employees.find((employee) => employee.id === employeeId)
  const employeeQuery = employeeSearch.trim().toLocaleLowerCase()
  const matchingEmployees = employees
    .filter((employee) => (
      !employeeQuery
      || `${employee.employeeNo} ${employee.fullName}`.toLocaleLowerCase().includes(employeeQuery)
    ))
    .slice(0, 50)

  async function reloadLoans() {
    onLoansChanged(await useCases.listEmployeeLoans(payrollGroupId))
  }

  async function createLoan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await useCases.createEmployeeLoan({
        employeeId,
        payrollGroupId,
        referenceNumber,
        principalAmount: Number(principal),
        installmentAmount: Number(installment),
        schedule,
        effectiveFrom,
      })
      await reloadLoans()
      setReferenceNumber('')
      setPrincipal('')
      setInstallment('')
      setNotice('Employee loan created.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the employee loan.')
    } finally {
      setSaving(false)
    }
  }

  async function retireLoan(loan: EmployeeLoan) {
    if (!window.confirm(`Retire loan ${loan.referenceNumber}? It will no longer generate payroll deductions.`)) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await useCases.retireEmployeeLoan(loan.id)
      await reloadLoans()
      setNotice(`Loan ${loan.referenceNumber} retired.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not retire the loan.')
    } finally {
      setSaving(false)
    }
  }

  async function restructureLoan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!restructuringLoan) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await useCases.restructureEmployeeLoan(restructuringLoan.id, {
        referenceNumber: restructureReference,
        additionalPrincipal: Number(additionalPrincipal),
        installmentAmount: Number(restructureInstallment),
        schedule: restructureSchedule,
        effectiveFrom: restructureDate,
      })
      await reloadLoans()
      setNotice(`Replacement loan created. The unpaid balance of ${restructuringLoan.referenceNumber} was rolled into it.`)
      setRestructuringLoan(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not restructure the loan.')
    } finally {
      setSaving(false)
    }
  }

  function startRestructure(loan: EmployeeLoan) {
    setRestructuringLoan(loan)
    setRestructureReference('')
    setAdditionalPrincipal('0')
    setRestructureInstallment(String(loan.installmentAmount))
    setRestructureSchedule(loan.schedule)
    setRestructureDate(today)
    setError('')
    setNotice('')
  }

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <header>
        <h2 className="text-lg font-bold text-slate-900">Employee loans</h2>
        <p className="mt-1 text-sm text-slate-500">
          Track loan reference numbers and balances. Scheduled installments are capped at the amount remaining and stop when paid.
        </p>
      </header>
      {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}

      <form onSubmit={(event) => void createLoan(event)} className="grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative">
          <label htmlFor="employee-loan-employee-search" className="text-xs font-semibold text-slate-600">
            Employee
          </label>
          <input
            id="employee-loan-employee-search"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={isEmployeeListOpen}
            aria-controls="employee-loan-employee-options"
            aria-label="Search employee by number or name"
            required
            autoComplete="off"
            value={employeeSearch || (selectedEmployee
              ? `${selectedEmployee.employeeNo} — ${selectedEmployee.fullName}`
              : '')}
            onFocus={(event) => {
              event.currentTarget.select()
              setIsEmployeeListOpen(true)
            }}
            onBlur={() => setIsEmployeeListOpen(false)}
            onChange={(event) => {
              setEmployeeSearch(event.target.value)
              setEmployeeId('')
              setIsEmployeeListOpen(true)
            }}
            placeholder={employees.length ? 'Search by employee number or name' : 'No employees available'}
            className={inputClass}
          />
          {isEmployeeListOpen && (
            <div
              id="employee-loan-employee-options"
              role="listbox"
              aria-label="Matching employees"
              className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
            >
              {matchingEmployees.length ? matchingEmployees.map((employee) => (
                <button
                  key={employee.id}
                  type="button"
                  role="option"
                  aria-selected={employee.id === employeeId}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setEmployeeId(employee.id)
                    setEmployeeSearch('')
                    setIsEmployeeListOpen(false)
                  }}
                  className="block w-full px-3 py-2 text-left hover:bg-indigo-50 focus:bg-indigo-50 focus:outline-none"
                >
                  <span className="block text-sm font-medium text-slate-800">{employee.fullName}</span>
                  <span className="block text-xs text-slate-500">{employee.employeeNo}</span>
                </button>
              )) : (
                <p className="px-3 py-2 text-sm font-normal text-slate-500">No employee matches that search.</p>
              )}
            </div>
          )}
        </div>
        <label className="text-xs font-semibold text-slate-600">
          Manual reference no.
          <input required maxLength={50} value={referenceNumber} onChange={(event) => setReferenceNumber(event.target.value)} className={inputClass} />
        </label>
        <label className="text-xs font-semibold text-slate-600">
          Principal (PHP)
          <input required type="number" min="0.01" step="0.01" value={principal} onChange={(event) => setPrincipal(event.target.value)} className={inputClass} />
        </label>
        <label className="text-xs font-semibold text-slate-600">
          Installment per occurrence (PHP)
          <input required type="number" min="0.01" step="0.01" value={installment} onChange={(event) => setInstallment(event.target.value)} className={inputClass} />
        </label>
        <label className="text-xs font-semibold text-slate-600">
          Payroll deduction timing
          <select value={schedule} onChange={(event) => setSchedule(event.target.value as EmployeeLoanSchedule)} className={inputClass}>
            {schedules.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold text-slate-600">
          Effective from
          <input required type="date" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} className={inputClass} />
        </label>
        <div className="flex items-end">
          <button disabled={saving || !employeeId} type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
            <Plus className="h-4 w-4" aria-hidden="true" /> {saving ? 'Saving…' : 'Create loan'}
          </button>
        </div>
      </form>

      {restructuringLoan && (
        <form onSubmit={(event) => void restructureLoan(event)} className="grid gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="text-sm text-amber-950 sm:col-span-2 lg:col-span-4">
            Restructuring <strong>{restructuringLoan.referenceNumber}</strong>: remaining balance {formatMoney(restructuringLoan.outstandingBalance)} will be added to the replacement principal.
          </div>
          <label className="text-xs font-semibold text-slate-600">
            New manual reference no.
            <input required maxLength={50} value={restructureReference} onChange={(event) => setRestructureReference(event.target.value)} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Additional principal (PHP)
            <input required type="number" min="0" step="0.01" value={additionalPrincipal} onChange={(event) => setAdditionalPrincipal(event.target.value)} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Installment per occurrence (PHP)
            <input required type="number" min="0.01" step="0.01" value={restructureInstallment} onChange={(event) => setRestructureInstallment(event.target.value)} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Payroll deduction timing
            <select value={restructureSchedule} onChange={(event) => setRestructureSchedule(event.target.value as EmployeeLoanSchedule)} className={inputClass}>
              {schedules.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Effective from
            <input required type="date" value={restructureDate} onChange={(event) => setRestructureDate(event.target.value)} className={inputClass} />
          </label>
          <div className="flex items-end gap-2">
            <button disabled={saving} type="submit" className="rounded-lg bg-amber-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {saving ? 'Saving…' : 'Create replacement loan'}
            </button>
            <button type="button" onClick={() => setRestructuringLoan(null)} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
              <X className="h-4 w-4" aria-hidden="true" /> Cancel
            </button>
          </div>
        </form>
      )}

      {loans.length === 0 ? (
        <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No employee loans have been recorded for this payroll group.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[70rem] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Employee / reference</th>
                <th className="px-3 py-2">Principal</th>
                <th className="px-3 py-2">Remaining</th>
                <th className="px-3 py-2">Installment / timing</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loans.map((loan) => {
                const employee = employees.find((item) => item.id === loan.employeeId)
                const cadence = schedules.find((item) => item.value === loan.schedule)?.label
                return (
                  <tr key={loan.id}>
                    <td className="px-3 py-3">
                      <span className="font-semibold text-slate-900">{loan.referenceNumber}</span>
                      <span className="block text-xs text-slate-500">{employee?.employeeNo ?? loan.employeeId} · {employee?.fullName ?? 'Employee record'}</span>
                      {loan.previousLoanId && <span className="block text-xs text-indigo-600">Restructured loan</span>}
                      {loan.repayments.length > 0 && (
                        <details className="mt-1 text-xs">
                          <summary className="cursor-pointer font-semibold text-indigo-700">
                            {loan.repayments.length} payroll repayment{loan.repayments.length === 1 ? '' : 's'}
                          </summary>
                          <ol className="mt-1 space-y-1 text-slate-600">
                            {loan.repayments.map((repayment) => (
                              <li key={repayment.id}>
                                {repayment.cutoffCode} · {formatMoney(repayment.amount)}
                              </li>
                            ))}
                          </ol>
                        </details>
                      )}
                    </td>
                    <td className="px-3 py-3">{formatMoney(loan.principalAmount)}</td>
                    <td className="px-3 py-3 font-semibold">{formatMoney(loan.outstandingBalance)}</td>
                    <td className="px-3 py-3">{formatMoney(loan.installmentAmount)}<span className="block text-xs text-slate-500">{cadence}</span></td>
                    <td className="px-3 py-3"><span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">{loan.status.replace('_', ' ')}</span></td>
                    <td className="px-3 py-3">
                      {loan.status === 'ACTIVE' && (
                        <div className="flex gap-2">
                          <button type="button" disabled={saving} onClick={() => startRestructure(loan)} className="rounded border border-indigo-200 px-2 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-60">Restructure</button>
                          <button type="button" disabled={saving} onClick={() => void retireLoan(loan)} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60">Retire</button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="flex items-start gap-2 text-xs text-slate-500">
        <Landmark className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        Payroll deductions are recorded against the loan by cutoff; recalculating a cutoff replaces its repayment entry.
      </p>
    </section>
  )
}
