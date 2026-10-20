import { useEffect, useState, type FormEvent } from 'react'
import { Pencil, Plus } from 'lucide-react'
import type { PayrollUseCases } from '../application/useCases'
import type { EmployeeCompensation, PayrollEmployeeOption } from '../domain/payroll'
import type { EmploymentAssignment } from '../../../types/employeeRelated'

interface Props {
  companyId: string
  payrollGroupId: string
  payrollGroupLabel: string
  useCases: PayrollUseCases
}

interface CompensationForm {
  employeeId: string
  baseRate: string
  currency: string
  effectiveFrom: string
  effectiveTo: string
}

const emptyForm: CompensationForm = {
  employeeId: '',
  baseRate: '',
  currency: 'PHP',
  effectiveFrom: '',
  effectiveTo: '',
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function formatRate(rate: number, currency: string) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(rate)
}

export default function CompensationManagement({ companyId, payrollGroupId, payrollGroupLabel, useCases }: Props) {
  const [employees, setEmployees] = useState<PayrollEmployeeOption[]>([])
  const [assignments, setAssignments] = useState<EmploymentAssignment[]>([])
  const [compensations, setCompensations] = useState<EmployeeCompensation[]>([])
  const [form, setForm] = useState<CompensationForm>(emptyForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let current = true
    setLoading(true)
    setError('')
    setEditingId(null)
    setForm(emptyForm)
    setSuccess('')
    Promise.all([
      useCases.listEmployees(),
      useCases.listCompanyEmploymentAssignments(companyId),
      useCases.listCompensations(payrollGroupId),
    ])
      .then(([nextEmployees, nextAssignments, nextCompensations]) => {
        if (!current) return
        const assignedEmployeeIds = new Set(
          nextAssignments
            .filter((assignment) =>
              assignment.is_active
              && assignment.status === 'ACTIVE'
              && assignment.payroll_group_id === payrollGroupId,
            )
            .map((assignment) => assignment.employee_id),
        )
        setAssignments(nextAssignments)
        setEmployees(nextEmployees.filter((employee) => employee.isActive && assignedEmployeeIds.has(employee.id)))
        setCompensations(nextCompensations)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load compensation setup.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [companyId, payrollGroupId, useCases])

  function setField<K extends keyof CompensationForm>(key: K, value: CompensationForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      const input = {
        employeeId: form.employeeId,
        payrollGroupId,
        baseRate: Number(form.baseRate),
        currency: form.currency.trim().toUpperCase(),
        effectiveFrom: form.effectiveFrom,
        effectiveTo: form.effectiveTo || null,
      }
      const saved = editingId
        ? await useCases.updateCompensation(editingId, input)
        : await useCases.createCompensation(input)
      setCompensations((current) =>
        [saved, ...current.filter((compensation) => compensation.id !== saved.id)]
          .sort((left, right) => right.effectiveFrom.localeCompare(left.effectiveFrom)),
      )
      setForm(emptyForm)
      setEditingId(null)
      setSuccess(editingId ? 'Employee compensation updated.' : 'Employee compensation saved.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save employee compensation.')
    } finally {
      setSaving(false)
    }
  }

  const employeeName = (employeeId: string) => {
    const employee = employees.find((item) => item.id === employeeId)
    return employee ? `${employee.employeeNo} — ${employee.fullName}` : employeeId
  }

  function editCompensation(compensation: EmployeeCompensation) {
    setError('')
    setSuccess('')
    setEditingId(compensation.id)
    setForm({
      employeeId: compensation.employeeId,
      baseRate: String(compensation.baseRate),
      currency: compensation.currency,
      effectiveFrom: compensation.effectiveFrom,
      effectiveTo: compensation.effectiveTo ?? '',
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(emptyForm)
    setError('')
    setSuccess('')
  }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-5">
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Compensation setup</p>
          <h2 className="mt-1 text-xl font-bold text-slate-900">Employee base rates</h2>
          <p className="mt-1 text-sm text-slate-500">
            {payrollGroupLabel}. Employees are limited to active assignments in the selected company and group. Compensation dates must be covered by exactly one assignment. Rates follow this group&apos;s monthly, daily, or hourly basis and must cover a full cutoff to calculate.
          </p>
        </div>
        {error && <p role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
          <label className="text-sm font-semibold text-slate-700 xl:col-span-2">
            Employee
            <select className={inputClass} required disabled={Boolean(editingId)} value={form.employeeId} onChange={(event) => setField('employeeId', event.target.value)}>
              <option value="">Select employee assigned to this group</option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>{employee.employeeNo} — {employee.fullName}</option>
              ))}
            </select>
          </label>
          <label className="text-sm font-semibold text-slate-700">
            Base rate
            <input className={inputClass} required type="number" min="0.01" step="0.01" value={form.baseRate} onChange={(event) => setField('baseRate', event.target.value)} />
          </label>
          <label className="text-sm font-semibold text-slate-700">
            Currency
            <input className={inputClass} required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" value={form.currency} onChange={(event) => setField('currency', event.target.value)} />
          </label>
          <label className="text-sm font-semibold text-slate-700">
            Effective from
            <input className={inputClass} required type="date" value={form.effectiveFrom} onChange={(event) => setField('effectiveFrom', event.target.value)} />
          </label>
          <label className="text-sm font-semibold text-slate-700">
            Effective to
            <input className={inputClass} type="date" min={form.effectiveFrom || undefined} value={form.effectiveTo} onChange={(event) => setField('effectiveTo', event.target.value)} />
          </label>
          <div className="flex items-end xl:col-span-6">
            <button type="submit" disabled={saving || loading || employees.length === 0} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
              <Plus className="h-4 w-4" aria-hidden="true" />
              {saving ? 'Saving…' : editingId ? 'Save changes' : 'Add base rate'}
            </button>
            {editingId && (
              <button type="button" onClick={cancelEdit} disabled={saving} className="ml-2 rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">
                Cancel
              </button>
            )}
          </div>
        </form>
        {!loading && employees.length === 0 && (
          <p className="mt-3 text-sm text-amber-700">
            No active employees have a current assignment in {payrollGroupLabel} for this company.
            {assignments.length === 0 ? ' Confirm that employee assignments include this company.' : ''}
          </p>
        )}
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-5 py-4">
          <h3 className="font-bold text-slate-900">Effective-dated rates</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-3">Employee</th>
                <th className="px-5 py-3">Base rate</th>
                <th className="px-5 py-3">Effective period</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && <tr><td colSpan={5} className="px-5 py-5 text-slate-500">Loading rates…</td></tr>}
              {!loading && compensations.length === 0 && <tr><td colSpan={5} className="px-5 py-5 text-slate-500">No compensation has been configured for this payroll group.</td></tr>}
              {compensations.map((compensation) => (
                <tr key={compensation.id}>
                  <td className="px-5 py-3 font-medium text-slate-800">{employeeName(compensation.employeeId)}</td>
                  <td className="px-5 py-3">{formatRate(compensation.baseRate, compensation.currency)}</td>
                  <td className="px-5 py-3">{compensation.effectiveFrom} → {compensation.effectiveTo ?? 'Ongoing'}</td>
                  <td className="px-5 py-3">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${compensation.isActive ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                      {compensation.isActive ? 'ACTIVE' : 'INACTIVE'}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <button
                      type="button"
                      onClick={() => editCompensation(compensation)}
                      disabled={saving || loading}
                      aria-label={`Edit compensation for ${employeeName(compensation.employeeId)}`}
                      title="Edit compensation"
                      className="rounded-md p-1.5 text-slate-500 transition hover:bg-indigo-50 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
