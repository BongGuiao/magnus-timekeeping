import { useEffect, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown, Pencil, Plus, Search } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { createPayrollCutoff, fetchPayrollCutoffs, updatePayrollCutoff } from '../lib/payrollCutoffApi'
import type { PayrollCutoff, PayrollCutoffPayload } from '../lib/payrollCutoffApi'
import { fetchPayrollGroups } from '../lib/payrollGroupApi'
import type { PayrollGroup } from '../lib/payrollGroupApi'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

interface CutoffForm {
  payroll_group_id: string
  cutoff_code: string
  period_start: string
  period_end: string
  pay_date: string
  employee_review_deadline: string
  supervisor_deadline: string
  hr_deadline: string
  status: string
  calculation_version: string
  export_batch_id: string
  is_active: boolean
}

type CutoffSortKey = 'cutoff' | 'period' | 'payDate' | 'deadlines' | 'status' | 'calculation'
type SortDirection = 'asc' | 'desc'

const blankForm: CutoffForm = {
  payroll_group_id: '',
  cutoff_code: '',
  period_start: '',
  period_end: '',
  pay_date: '',
  employee_review_deadline: '',
  supervisor_deadline: '',
  hr_deadline: '',
  status: 'SCHEDULED',
  calculation_version: '',
  export_batch_id: '',
  is_active: true,
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function toLocalDateTime(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return localDate.toISOString().slice(0, 16)
}

function toUtcDateTime(value: string) {
  return value ? new Date(value).toISOString() : null
}

function groupLabel(groupId: string, groups: PayrollGroup[]) {
  const group = groups.find((item) => item.id === groupId)
  return group ? `${group.payroll_group_code} — ${group.payroll_group_name}` : 'Payroll group unavailable'
}

function deadlineText(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export default function PayrollCutoffs({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [groups, setGroups] = useState<PayrollGroup[]>([])
  const [cutoffs, setCutoffs] = useState<PayrollCutoff[]>([])
  const [form, setForm] = useState<CutoffForm>(blankForm)
  const [editing, setEditing] = useState<PayrollCutoff | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<CutoffSortKey>('period')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    setEditing(null)
    setIsFormOpen(false)
    setForm(blankForm)
  }, [companyId])

  useEffect(() => {
    let current = true
    setLoading(true)
    const loadCompanyCutoffs = async () => {
      const companyGroups = companyId ? await fetchPayrollGroups(companyId) : []
      if (!current) return
      setGroups(companyGroups)
      const groupedCutoffs = await Promise.all(
        companyGroups.map((group) => fetchPayrollCutoffs(group.id)),
      )
      if (current) setCutoffs(groupedCutoffs.flat())
    }
    loadCompanyCutoffs()
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load payroll cutoffs.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [companyId])

  function setField<K extends keyof CutoffForm>(key: K, value: CutoffForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function resetForm() {
    setEditing(null)
    setIsFormOpen(false)
    setForm({
      ...blankForm,
      payroll_group_id: groups.find((group) => group.is_active && group.status === 'ACTIVE')?.id ?? '',
    })
    setError('')
    setSuccess('')
  }

  function beginEdit(cutoff: PayrollCutoff) {
    setEditing(cutoff)
    setIsFormOpen(true)
    setForm({
      payroll_group_id: cutoff.payroll_group_id,
      cutoff_code: cutoff.cutoff_code,
      period_start: cutoff.period_start,
      period_end: cutoff.period_end,
      pay_date: cutoff.pay_date,
      employee_review_deadline: toLocalDateTime(cutoff.employee_review_deadline),
      supervisor_deadline: toLocalDateTime(cutoff.supervisor_deadline),
      hr_deadline: toLocalDateTime(cutoff.hr_deadline),
      status: cutoff.status,
      calculation_version: cutoff.calculation_version ?? '',
      export_batch_id: cutoff.export_batch_id ?? '',
      is_active: cutoff.is_active,
    })
    setError('')
    setSuccess('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    setSaving(true)
    const payload: PayrollCutoffPayload = {
      payroll_group_id: form.payroll_group_id,
      cutoff_code: form.cutoff_code.trim(),
      period_start: form.period_start,
      period_end: form.period_end,
      pay_date: form.pay_date,
      employee_review_deadline: toUtcDateTime(form.employee_review_deadline),
      supervisor_deadline: toUtcDateTime(form.supervisor_deadline),
      hr_deadline: toUtcDateTime(form.hr_deadline),
      status: form.status.trim(),
      calculation_version: form.calculation_version.trim() || null,
      export_batch_id: form.export_batch_id.trim() || null,
      is_active: form.is_active,
    }
    try {
      if (editing) await updatePayrollCutoff(editing.id, payload)
      else await createPayrollCutoff(payload)
      const groupedCutoffs = await Promise.all(groups.map((group) => fetchPayrollCutoffs(group.id)))
      setCutoffs(groupedCutoffs.flat())
      resetForm()
      setSuccess(editing ? 'Payroll cutoff updated.' : 'Payroll cutoff created.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the payroll cutoff.')
    } finally {
      setSaving(false)
    }
  }

  const activeGroups = groups.filter((group) => group.is_active && group.status === 'ACTIVE')
  const normalizedSearch = search.trim().toLowerCase()
  const filteredCutoffs = normalizedSearch
    ? cutoffs.filter((cutoff) => [
      cutoff.cutoff_code,
      groupLabel(cutoff.payroll_group_id, groups),
      cutoff.period_start,
      cutoff.period_end,
      cutoff.pay_date,
      cutoff.status,
      cutoff.calculation_version,
    ].some((value) => String(value ?? '').toLowerCase().includes(normalizedSearch)))
    : cutoffs
  const visibleCutoffs = [...filteredCutoffs].sort((left, right) => {
    const sortValues: Record<CutoffSortKey, [string | number, string | number]> = {
      cutoff: [left.cutoff_code, right.cutoff_code],
      period: [`${left.period_start} ${left.period_end}`, `${right.period_start} ${right.period_end}`],
      payDate: [left.pay_date, right.pay_date],
      deadlines: [
        [left.employee_review_deadline, left.supervisor_deadline, left.hr_deadline].filter(Boolean).sort()[0] ?? '',
        [right.employee_review_deadline, right.supervisor_deadline, right.hr_deadline].filter(Boolean).sort()[0] ?? '',
      ],
      status: [`${left.status} ${left.is_active} ${left.locked_at ?? ''}`, `${right.status} ${right.is_active} ${right.locked_at ?? ''}`],
      calculation: [`${left.calculation_version ?? ''} ${left.export_batch_id ?? ''}`, `${right.calculation_version ?? ''} ${right.export_batch_id ?? ''}`],
    }
    let [leftValue, rightValue] = sortValues[sortKey]
    if (sortKey === 'cutoff') {
      leftValue = `${left.cutoff_code} ${groupLabel(left.payroll_group_id, groups)}`
      rightValue = `${right.cutoff_code} ${groupLabel(right.payroll_group_id, groups)}`
    }
    const comparison = typeof leftValue === 'number' && typeof rightValue === 'number'
      ? leftValue - rightValue
      : String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true })
    return sortDirection === 'asc' ? comparison : -comparison
  })

  function changeSort(key: CutoffSortKey) {
    if (sortKey === key) {
      setSortDirection((direction) => direction === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  function sortHeader(label: string, key: CutoffSortKey) {
    const active = sortKey === key
    const direction = active ? sortDirection : null
    return (
      <button
        type="button"
        onClick={() => changeSort(key)}
        aria-label={`Sort by ${label}${direction ? `, ${direction === 'asc' ? 'ascending' : 'descending'}` : ''}`}
        className="inline-flex items-center gap-1.5 text-left hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        {label}
        {!active
          ? <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
          : direction === 'asc'
            ? <ArrowUp className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />
            : <ArrowDown className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />}
      </button>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="payroll-cutoffs" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-3 py-6">
        {!isFormOpen && <p className="text-xs text-slate-500">Schedule payroll periods, pay dates, and review deadlines by payroll group.</p>}

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!isFormOpen && success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        {isFormOpen && <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit cutoff' : 'Add cutoff'}</h2>
          </div>
          <form onSubmit={submit} className="grid gap-4 md:grid-cols-3">
            <label className="text-sm font-semibold text-slate-700">Payroll group
              <select className={inputClass} required value={form.payroll_group_id} onChange={(event) => setField('payroll_group_id', event.target.value)}>
                <option value="">Select payroll group</option>
                {(editing ? groups : activeGroups).map((group) => (
                  <option key={group.id} value={group.id}>{group.payroll_group_code} — {group.payroll_group_name}</option>
                ))}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Cutoff code
              <input className={inputClass} maxLength={50} required value={form.cutoff_code} onChange={(event) => setField('cutoff_code', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Status
              <input className={inputClass} maxLength={30} required value={form.status} onChange={(event) => setField('status', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Period start
              <input className={inputClass} type="date" required value={form.period_start} onChange={(event) => setField('period_start', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Period end
              <input className={inputClass} type="date" min={form.period_start} required value={form.period_end} onChange={(event) => setField('period_end', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Pay date
              <input className={inputClass} type="date" required value={form.pay_date} onChange={(event) => setField('pay_date', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Employee review deadline
              <input className={inputClass} type="datetime-local" value={form.employee_review_deadline} onChange={(event) => setField('employee_review_deadline', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Supervisor deadline
              <input className={inputClass} type="datetime-local" value={form.supervisor_deadline} onChange={(event) => setField('supervisor_deadline', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">HR deadline
              <input className={inputClass} type="datetime-local" value={form.hr_deadline} onChange={(event) => setField('hr_deadline', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Calculation version (optional)
              <input className={inputClass} maxLength={50} value={form.calculation_version} onChange={(event) => setField('calculation_version', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Export batch ID (optional)
              <input className={inputClass} type="text" placeholder="UUID" value={form.export_batch_id} onChange={(event) => setField('export_batch_id', event.target.value)} />
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm font-semibold text-slate-700">
              <input type="checkbox" checked={form.is_active} onChange={(event) => setField('is_active', event.target.checked)} />
              Active
            </label>
            <div className="flex justify-end gap-2 md:col-span-3">
              <button type="button" onClick={resetForm} className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
              <button type="submit" disabled={saving || loading || groups.length === 0} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
                <Plus className="h-4 w-4" aria-hidden="true" />
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Add cutoff'}
              </button>
            </div>
          </form>
        </section>}

        {!isFormOpen && <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-200 bg-slate-100 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <label className="relative block w-full sm:max-w-sm">
              <span className="sr-only">Search payroll cutoffs</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search payroll cutoffs" className="w-full rounded-md border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
            </label>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              {!isFormOpen && <button type="button" onClick={() => { resetForm(); setIsFormOpen(true) }} disabled={loading || activeGroups.length === 0} className="inline-flex items-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"><Plus className="h-4 w-4" /> New cutoff</button>}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th scope="col" aria-sort={sortKey === 'cutoff' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3">{sortHeader('Cutoff / Group', 'cutoff')}</th>
                  <th scope="col" aria-sort={sortKey === 'period' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3">{sortHeader('Period', 'period')}</th>
                  <th scope="col" aria-sort={sortKey === 'payDate' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3">{sortHeader('Pay date', 'payDate')}</th>
                  <th scope="col" aria-sort={sortKey === 'deadlines' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3">{sortHeader('Review deadlines', 'deadlines')}</th>
                  <th scope="col" aria-sort={sortKey === 'status' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3">{sortHeader('Status / lock', 'status')}</th>
                  <th scope="col" aria-sort={sortKey === 'calculation' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3">{sortHeader('Calculation', 'calculation')}</th>
                  <th className="px-4 py-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading && <tr><td colSpan={7} className="px-4 py-5 text-slate-500">Loading cutoffs…</td></tr>}
                {!loading && visibleCutoffs.length === 0 && <tr><td colSpan={7} className="px-4 py-5 text-slate-500">{normalizedSearch ? 'No cutoffs match your search.' : 'No cutoffs configured.'}</td></tr>}
                {visibleCutoffs.map((cutoff) => (
                  <tr key={cutoff.id} className={editing?.id === cutoff.id ? 'bg-indigo-50' : ''}>
                    <td className="px-4 py-3"><p className="font-semibold text-slate-900">{cutoff.cutoff_code}</p><p className="text-xs text-slate-500">{groupLabel(cutoff.payroll_group_id, groups)}</p></td>
                    <td className="px-4 py-3">{cutoff.period_start} → {cutoff.period_end}</td>
                    <td className="px-4 py-3">{cutoff.pay_date}</td>
                    <td className="px-4 py-3 text-xs">
                      <p>Employee: {deadlineText(cutoff.employee_review_deadline)}</p>
                      <p>Supervisor: {deadlineText(cutoff.supervisor_deadline)}</p>
                      <p>HR: {deadlineText(cutoff.hr_deadline)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
                        cutoff.is_active && cutoff.status === 'ACTIVE'
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'bg-slate-100 text-slate-600'
                      }`}>
                        {cutoff.status}{!cutoff.is_active ? ' · INACTIVE' : ''}
                      </span>
                      {cutoff.locked_at && <p className="text-xs text-amber-700">Locked {deadlineText(cutoff.locked_at)}</p>}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      <p>{cutoff.calculation_version ?? '—'}</p>
                      {cutoff.export_batch_id && <p className="text-slate-500">Exported</p>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button type="button" onClick={() => beginEdit(cutoff)} aria-label={`Edit ${cutoff.cutoff_code}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700">
                        <Pencil className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>}
      </main>
    </div>
  )
}
