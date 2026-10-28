import { useEffect, useState, type FormEvent } from 'react'
import { Pencil, Plus } from 'lucide-react'
import DataTable from '../components/common/DataTable'
import type { DataTableColumn } from '../components/common/DataTable'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { useCompanySetupSelection } from '../hooks/useCompanySetupSelection'
import { fetchCompanies } from '../lib/companyApi'
import { createLeaveType, fetchLeaveTypes, updateLeaveType } from '../lib/leaveApi'
import { leaveUnitsToMinutes, minutesToLeaveUnits } from '../lib/leaveApi'
import type { LeaveType, LeaveTypePayload, LeaveUnitType } from '../lib/leaveApi'
import type { Company } from '../types/company'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const blankForm: LeaveTypePayload = {
  company_id: '',
  leave_code: '',
  leave_name: '',
  leave_category: 'ANNUAL',
  unit_type: 'MINUTES',
  annual_entitlement_minutes: 0,
  accrual_method: 'ANNUAL',
  minimum_service_months: 0,
  allow_negative_balance: false,
  maximum_negative_minutes: 0,
  carryover_allowed: false,
  maximum_carryover_minutes: 0,
  expiry_rule: 'NONE',
  cash_conversion_allowed: false,
  advance_notice_days: 0,
  document_required: false,
  document_trigger_minutes: 0,
  exclude_rest_days: true,
  exclude_holidays: true,
  effective_from: (() => {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  })(),
  effective_to: null,
  status: 'ACTIVE',
  is_active: true,
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function Minutes({ value }: { value: number }) {
  const hours = Math.floor(value / 60)
  const minutes = value % 60
  return <>{value.toLocaleString()} min ({hours}h {minutes}m)</>
}

function unitLabel(unit: LeaveUnitType) {
  return unit === 'DAYS' ? 'days' : unit === 'HOURS' ? 'hours' : 'minutes'
}

function formatLeaveUnits(minutes: number, unit: LeaveUnitType) {
  return `${minutesToLeaveUnits(minutes, unit).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(unit)}`
}

export default function LeaveManagement({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const { companyId } = useCompanySetupSelection()
  const [companies, setCompanies] = useState<Company[]>([])
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [form, setForm] = useState<LeaveTypePayload>(blankForm)
  const [editing, setEditing] = useState<LeaveType | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function reload() {
    const [nextCompanies, nextTypes] = await Promise.all([fetchCompanies(), fetchLeaveTypes()])
    setCompanies(nextCompanies)
    setLeaveTypes(companyId ? nextTypes.filter((item) => item.company_id === companyId) : [])
    if (!editing) setForm((current) => ({ ...current, company_id: companyId }))
  }

  useEffect(() => {
    setEditing(null)
    setIsFormOpen(false)
    setForm({ ...blankForm, company_id: companyId })
    Promise.all([fetchCompanies(), fetchLeaveTypes()])
      .then(([nextCompanies, nextTypes]) => {
        setCompanies(nextCompanies)
        setLeaveTypes(companyId ? nextTypes.filter((item) => item.company_id === companyId) : [])
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Could not load leave configuration.'))
      .finally(() => setLoading(false))
  }, [companyId])

  function resetForm() {
    setEditing(null)
    setIsFormOpen(false)
    setForm({ ...blankForm, company_id: companyId })
  }

  function beginEdit(item: LeaveType) {
    setEditing(item)
    setIsFormOpen(true)
    setForm({
      ...item,
      effective_to: item.effective_to ?? null,
    })
    setError('')
    setSuccess('')
  }

  function setField<K extends keyof LeaveTypePayload>(key: K, value: LeaveTypePayload[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function setUnitAmount(
    key: 'annual_entitlement_minutes' | 'maximum_negative_minutes' | 'maximum_carryover_minutes' | 'document_trigger_minutes',
    value: string,
  ) {
    const minutes = leaveUnitsToMinutes(Number(value), form.unit_type)
    setField(key, minutes)
  }

  function unitAmount(minutes: number) {
    return Number(minutesToLeaveUnits(minutes, form.unit_type).toFixed(3))
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      if (editing) await updateLeaveType(editing.id, form)
      else await createLeaveType(form)
      await reload()
      resetForm()
      setSuccess(editing ? 'Leave type updated.' : 'Leave type created.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this leave type.')
    } finally {
      setSaving(false)
    }
  }

  const columns: DataTableColumn<LeaveType>[] = [
    {
      key: 'leave',
      header: 'Code / Name',
      value: (item) => `${item.leave_code} ${item.leave_name}`,
      render: (item) => (
        <div>
          <p className="font-bold text-slate-900">{item.leave_code}</p>
          <p className="text-slate-500">{item.leave_name}</p>
        </div>
      ),
    },
    {
      key: 'company',
      header: 'Company',
      value: (item) => companies.find((company) => company.id === item.company_id)?.legal_name ?? '',
    },
    { key: 'category', header: 'Category', value: (item) => item.leave_category },
    {
      key: 'entitlement',
      header: 'Annual entitlement',
      value: (item) => `${item.annual_entitlement_minutes} ${item.unit_type}`,
      render: (item) => (
        <div>
          {item.unit_type === 'MINUTES'
            ? <Minutes value={item.annual_entitlement_minutes} />
            : formatLeaveUnits(item.annual_entitlement_minutes, item.unit_type)}
          {item.unit_type !== 'MINUTES' && <span className="block text-xs text-slate-500"><Minutes value={item.annual_entitlement_minutes} /></span>}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      value: (item) => `${item.status} ${item.is_active ? 'active' : 'inactive'}`,
      render: (item) => (
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${
          item.is_active && item.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
        }`}>
          {item.status}{!item.is_active ? ' · INACTIVE' : ''}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      value: () => '',
      sortable: false,
      searchable: false,
      render: (item) => (
        <button type="button" onClick={() => beginEdit(item)} aria-label={`Edit ${item.leave_code}`} className="inline-flex items-center gap-1 rounded-md p-2 font-semibold text-indigo-700 hover:bg-indigo-50 hover:text-indigo-900">
          <Pencil className="h-4 w-4" />
        </button>
      ),
    },
  ]

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="leave-management" onNavigate={onNavigate} onSignOut={logout} />
      <main className="w-full space-y-3 px-4 py-6 sm:px-6 lg:px-8">
        {!isFormOpen && <p className="text-xs text-slate-500">Configure company leave policies and entitlements in minutes.</p>}

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!isFormOpen && success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}

        {isFormOpen && <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit leave type' : 'Add leave type'}</h2>
          </div>
          <form onSubmit={submit} className="grid gap-4 md:grid-cols-3">
            <label className="text-sm font-semibold text-slate-700">Company
              <select className={inputClass} required disabled={Boolean(companyId)} value={form.company_id} onChange={(event) => setField('company_id', event.target.value)}>
                <option value="">Select company</option>
                {companies.filter((company) => !companyId || company.id === companyId).map((company) => <option key={company.id} value={company.id}>{company.legal_name}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Leave code
              <input className={inputClass} maxLength={30} required value={form.leave_code} onChange={(event) => setField('leave_code', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Leave name
              <input className={inputClass} maxLength={150} required value={form.leave_name} onChange={(event) => setField('leave_name', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Category
              <input className={inputClass} maxLength={30} required value={form.leave_category} onChange={(event) => setField('leave_category', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Unit type
              <select
                className={inputClass}
                value={form.unit_type}
                onChange={(event) => {
                  const value = event.target.value
                  if (value === 'MINUTES' || value === 'DAYS' || value === 'HOURS') setField('unit_type', value)
                }}
              >
                <option value="MINUTES">Minutes</option><option value="DAYS">Days</option><option value="HOURS">Hours</option>
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Accrual method
              <input className={inputClass} maxLength={30} required value={form.accrual_method} onChange={(event) => setField('accrual_method', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Annual entitlement ({unitLabel(form.unit_type)})
              <input className={inputClass} type="number" min={0} step="any" required value={unitAmount(form.annual_entitlement_minutes)} onChange={(event) => setUnitAmount('annual_entitlement_minutes', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Minimum service (months)
              <input className={inputClass} type="number" min={0} value={form.minimum_service_months} onChange={(event) => setField('minimum_service_months', Number(event.target.value))} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Advance notice (days)
              <input className={inputClass} type="number" min={0} value={form.advance_notice_days} onChange={(event) => setField('advance_notice_days', Number(event.target.value))} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Maximum negative balance ({unitLabel(form.unit_type)})
              <input className={inputClass} type="number" min={0} step="any" value={unitAmount(form.maximum_negative_minutes)} onChange={(event) => setUnitAmount('maximum_negative_minutes', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Maximum carryover ({unitLabel(form.unit_type)})
              <input className={inputClass} type="number" min={0} step="any" value={unitAmount(form.maximum_carryover_minutes)} onChange={(event) => setUnitAmount('maximum_carryover_minutes', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Document trigger ({unitLabel(form.unit_type)})
              <input className={inputClass} type="number" min={0} step="any" value={unitAmount(form.document_trigger_minutes)} onChange={(event) => setUnitAmount('document_trigger_minutes', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Expiry rule
              <input className={inputClass} maxLength={30} required value={form.expiry_rule} onChange={(event) => setField('expiry_rule', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Effective from
              <input className={inputClass} type="date" required value={form.effective_from} onChange={(event) => setField('effective_from', event.target.value)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Effective to
              <input className={inputClass} type="date" value={form.effective_to ?? ''} onChange={(event) => setField('effective_to', event.target.value || null)} />
            </label>
            <label className="text-sm font-semibold text-slate-700">Status
              <select className={inputClass} value={form.status} onChange={(event) => setField('status', event.target.value)}>
                <option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option><option value="DRAFT">Draft</option>
              </select>
            </label>
            <div className="flex flex-wrap gap-x-5 gap-y-2 md:col-span-3">
              {([
                ['allow_negative_balance', 'Allow negative balance'],
                ['carryover_allowed', 'Allow carryover'],
                ['cash_conversion_allowed', 'Allow cash conversion'],
                ['document_required', 'Document required'],
                ['exclude_rest_days', 'Exclude rest days'],
                ['exclude_holidays', 'Exclude holidays'],
                ['is_active', 'Active'],
              ] as const).map(([key, label]) => (
                <label key={key} className="inline-flex items-center gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={form[key]} onChange={(event) => setField(key, event.target.checked)} /> {label}
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2 md:col-span-3">
              <button type="button" onClick={resetForm} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Cancel</button>
              <button disabled={saving || !companyId} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
                <Plus className="h-4 w-4" /> {saving ? 'Saving…' : editing ? 'Save changes' : 'Create leave type'}
              </button>
            </div>
          </form>
        </section>}

        {!isFormOpen && <DataTable
          rows={leaveTypes}
          columns={columns}
          getRowKey={(item) => item.id}
          searchPlaceholder="Search leave types"
          emptyMessage={loading ? 'Loading leave types…' : 'No leave types configured.'}
          toolbar={!isFormOpen ? (
            <button type="button" onClick={() => {
              resetForm()
              setIsFormOpen(true)
            }} disabled={loading || !companyId} className="inline-flex items-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
              <Plus className="h-4 w-4" /> New leave type
            </button>
          ) : undefined}
        />}
      </main>
    </div>
  )
}
