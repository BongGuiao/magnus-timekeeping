import { useEffect, useState, type FormEvent } from 'react'
import { Pencil, Plus } from 'lucide-react'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import {
  createPayrollGroup,
  fetchPayrollGroups,
  fetchPayrollHolidayCalendars,
  updatePayrollGroup,
} from '../lib/payrollGroupApi'
import type {
  HolidayCalendarOption,
  PayrollGroup,
  PayrollGroupPayload,
  PayrollPayFrequency,
  PayrollRateType,
} from '../lib/payrollGroupApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const blankForm: PayrollGroupPayload = {
  company_id: '',
  payroll_group_code: '',
  payroll_group_name: '',
  pay_frequency: 'MONTHLY',
  rate_type: 'MONTHLY',
  standard_minutes_per_day: 480,
  annual_divisor: null,
  rounding_minutes: 1,
  holiday_calendar_id: null,
  status: 'ACTIVE',
  is_active: true,
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const payFrequencies: PayrollPayFrequency[] = ['WEEKLY', 'BIWEEKLY', 'SEMIMONTHLY', 'MONTHLY']
const rateTypes: PayrollRateType[] = ['MONTHLY', 'DAILY', 'HOURLY']

function companyName(companyId: string, companies: Company[]) {
  return companies.find((company) => company.id === companyId)?.legal_name ?? companyId
}

function calendarName(calendarId: string | null, calendars: HolidayCalendarOption[]) {
  if (!calendarId) return 'None'
  const calendar = calendars.find((option) => option.id === calendarId)
  return calendar ? `${calendar.calendar_code} — ${calendar.calendar_name}` : calendarId
}

export default function PayrollGroups({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [groups, setGroups] = useState<PayrollGroup[]>([])
  const [calendars, setCalendars] = useState<HolidayCalendarOption[]>([])
  const [form, setForm] = useState<PayrollGroupPayload>(blankForm)
  const [editing, setEditing] = useState<PayrollGroup | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function reloadGroups() {
    const nextGroups = companyId ? await fetchPayrollGroups(companyId) : []
    setGroups(nextGroups)
  }

  useEffect(() => {
    setEditing(null)
    setIsFormOpen(false)
    setForm({ ...blankForm, company_id: companyId })
    Promise.all([fetchCompanies(), companyId ? fetchPayrollGroups(companyId) : Promise.resolve([])])
      .then(([nextCompanies, nextGroups]) => {
        setCompanies(nextCompanies)
        setGroups(nextGroups)
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Could not load payroll configuration.'))
      .finally(() => setLoading(false))
  }, [companyId])

  useEffect(() => {
    if (!form.company_id) return
    let current = true
    fetchPayrollHolidayCalendars(form.company_id)
      .then((nextCalendars) => {
        if (current) setCalendars(nextCalendars)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load holiday calendars.')
      })
    return () => {
      current = false
    }
  }, [form.company_id])

  function setField<K extends keyof PayrollGroupPayload>(key: K, value: PayrollGroupPayload[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function resetForm() {
    setEditing(null)
    setIsFormOpen(false)
    setForm({
      ...blankForm,
      company_id: companyId,
    })
    setError('')
    setSuccess('')
  }

  function beginEdit(group: PayrollGroup) {
    setEditing(group)
    setIsFormOpen(true)
    setForm({
      company_id: group.company_id,
      payroll_group_code: group.payroll_group_code,
      payroll_group_name: group.payroll_group_name,
      pay_frequency: group.pay_frequency,
      rate_type: group.rate_type,
      standard_minutes_per_day: group.standard_minutes_per_day,
      annual_divisor: group.annual_divisor,
      rounding_minutes: group.rounding_minutes,
      holiday_calendar_id: group.holiday_calendar_id,
      status: group.status,
      is_active: group.is_active,
    })
    setError('')
    setSuccess('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      const payload = {
        ...form,
        payroll_group_code: form.payroll_group_code.trim(),
        payroll_group_name: form.payroll_group_name.trim(),
        annual_divisor: form.annual_divisor === null ? null : Number(form.annual_divisor),
      }
      if (editing) await updatePayrollGroup(editing.id, payload)
      else await createPayrollGroup(payload)
      await reloadGroups()
      resetForm()
      setSuccess(editing ? 'Payroll group updated.' : 'Payroll group created.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the payroll group.')
    } finally {
      setSaving(false)
    }
  }

  const columns: DataTableColumn<PayrollGroup>[] = [
    {
      key: 'group',
      header: 'Company / Group',
      value: (group) => `${group.payroll_group_code} ${group.payroll_group_name} ${companyName(group.company_id, companies)}`,
      render: (group) => (
        <div>
          <p className="font-semibold text-slate-900">{group.payroll_group_code} — {group.payroll_group_name}</p>
          <p className="text-xs text-slate-500">{companyName(group.company_id, companies)}</p>
        </div>
      ),
    },
    { key: 'frequency', header: 'Frequency', value: (group) => group.pay_frequency },
    { key: 'rate', header: 'Rate type', value: (group) => group.rate_type },
    { key: 'minutes', header: 'Minutes / day', value: (group) => group.standard_minutes_per_day },
    { key: 'divisor', header: 'Annual divisor', value: (group) => group.annual_divisor ?? '', render: (group) => group.annual_divisor?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—' },
    { key: 'rounding', header: 'Rounding', value: (group) => group.rounding_minutes, render: (group) => `${group.rounding_minutes.toLocaleString()} min` },
    { key: 'calendar', header: 'Holiday calendar', value: (group) => calendarName(group.holiday_calendar_id, calendars) },
    {
      key: 'status',
      header: 'Status',
      value: (group) => `${group.status} ${group.is_active}`,
      render: (group) => (
        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${group.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
          {group.status}{group.is_active ? '' : ' · INACTIVE'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (group) => (
        <button type="button" onClick={() => beginEdit(group)} aria-label={`Edit ${group.payroll_group_code}`} className="rounded-md p-2 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700">
          <Pencil className="h-4 w-4" />
        </button>
      ),
    },
  ]

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="payroll-groups" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-3 py-6">
        {!isFormOpen && <p className="text-xs text-slate-500">Configure pay frequency, rate basis, workday minutes, and rounding for each company.</p>}

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!isFormOpen && success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        {isFormOpen && <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit payroll group' : 'Add payroll group'}</h2>
          </div>
          <form onSubmit={submit} className="grid gap-4 md:grid-cols-3">
            <label className="text-sm font-semibold text-slate-700">Company
              <select className={inputClass} required disabled={Boolean(companyId)} value={form.company_id} onChange={(event) => {
                setField('company_id', event.target.value)
                setField('holiday_calendar_id', null)
              }}>
                <option value="">Select company</option>
                {companies.filter((company) => company.id === companyId || (!companyId && (company.is_active || company.id === form.company_id))).map((company) => <option key={company.id} value={company.id}>{company.legal_name}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Group code
              <input className={inputClass} maxLength={30} required value={form.payroll_group_code} onChange={(event) => setField('payroll_group_code', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Group name
              <input className={inputClass} maxLength={100} required value={form.payroll_group_name} onChange={(event) => setField('payroll_group_name', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Pay frequency
              <select className={inputClass} value={form.pay_frequency} onChange={(event) => setField('pay_frequency', event.target.value as PayrollPayFrequency)}>
                {payFrequencies.map((frequency) => <option key={frequency} value={frequency}>{frequency}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Rate type
              <select className={inputClass} value={form.rate_type} onChange={(event) => setField('rate_type', event.target.value as PayrollRateType)}>
                {rateTypes.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Standard minutes per day
              <input className={inputClass} type="number" min={1} step={1} required value={form.standard_minutes_per_day} onChange={(event) => setField('standard_minutes_per_day', Number(event.target.value))} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Annual divisor (optional)
              <input className={inputClass} type="number" min="0.01" max="99999999.99" step="0.01" value={form.annual_divisor ?? ''} onChange={(event) => setField('annual_divisor', event.target.value === '' ? null : Number(event.target.value))} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Rounding minutes
              <input className={inputClass} type="number" min={1} step={1} required value={form.rounding_minutes} onChange={(event) => setField('rounding_minutes', Number(event.target.value))} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Holiday calendar (optional)
              <select className={inputClass} value={form.holiday_calendar_id ?? ''} onChange={(event) => setField('holiday_calendar_id', event.target.value || null)}>
                <option value="">No holiday calendar</option>
                {calendars.map((calendar) => (
                  <option key={calendar.id} value={calendar.id}>{calendar.calendar_code} — {calendar.calendar_name} ({calendar.effective_year})</option>
                ))}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Status
              <input className={inputClass} maxLength={20} required value={form.status} onChange={(event) => setField('status', event.target.value)} />
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm font-semibold text-slate-700">
              <input type="checkbox" checked={form.is_active} onChange={(event) => setField('is_active', event.target.checked)} />
              Active
            </label>
            <div className="flex justify-end gap-2 md:col-span-3">
              <button type="button" onClick={resetForm} className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
              <button type="submit" disabled={saving || loading || !companyId} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
                <Plus className="h-4 w-4" aria-hidden="true" />
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Add payroll group'}
              </button>
            </div>
          </form>
          {!loading && companies.length === 0 && <p className="mt-3 text-sm text-amber-700">Create a company before configuring payroll groups.</p>}
        </section>}

        {!isFormOpen && <DataTable
          rows={groups}
          columns={columns}
          getRowKey={(group) => group.id}
          searchPlaceholder="Search payroll groups"
          emptyMessage={loading ? 'Loading payroll groups…' : 'No payroll groups configured.'}
          toolbar={!isFormOpen ? (
            <button type="button" onClick={() => { resetForm(); setIsFormOpen(true) }} disabled={loading || !companyId} className="inline-flex items-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
              <Plus className="h-4 w-4" /> New payroll group
            </button>
          ) : undefined}
        />}
      </main>
    </div>
  )
}
