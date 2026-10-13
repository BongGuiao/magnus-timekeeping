import { useEffect, useState, type FormEvent } from 'react'
import { Pencil, X } from 'lucide-react'
import TopNav from '../components/dashboard/TopNav'
import type { NavView } from '../components/dashboard/TopNav'
import { useLogout } from '../hooks/useLogout'
import { fetchEmployees } from '../lib/employeeApi'
import { fetchCurrentEmploymentAssignment, getCompletedServiceMonths, getManilaDate } from '../lib/employeeRelatedApi'
import {
  calculateAvailableMinutes,
  createEmployeeEntitlement,
  fetchEmployeeEntitlements,
  fetchLeaveTypes,
  formatLeaveBalance,
  leaveUnitsToMinutes,
  minutesToLeaveUnits,
  updateEmployeeEntitlement,
} from '../lib/leaveApi'
import type { LeaveUnitType } from '../lib/leaveApi'
import type { EmployeeEntitlement, EmployeeEntitlementPayload, LeaveType } from '../lib/leaveApi'
import type { Employee } from '../types/employee'

interface Props {
  employeeName: string
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const blankForm: EmployeeEntitlementPayload = {
  employee_id: '',
  leave_type_id: '',
  entitlement_year: new Date().getFullYear(),
  opening_minutes: 0,
  granted_minutes: 0,
  accrued_minutes: 0,
  carryover_minutes: 0,
  adjustment_minutes: 0,
  used_minutes: 0,
  reserved_minutes: 0,
  expired_minutes: 0,
  converted_minutes: 0,
  available_minutes: 0,
  last_calculated_at: null,
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function formatUnit(unit: LeaveUnitType) {
  return unit.toLowerCase()
}

function amountStep(unit: LeaveUnitType) {
  return unit === 'MINUTES' ? 1 : 0.001
}

function employeeLabel(employee: Employee) {
  return `${employee.employee_no} — ${employee.preferred_name || `${employee.first_name} ${employee.last_name}`}`
}

export default function EmployeeEntitlements({ employeeName, onNavigate, onLoggedOut }: Props) {
  const { logout } = useLogout({ onLoggedOut })
  const [employees, setEmployees] = useState<Employee[]>([])
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [assignment, setAssignment] = useState<Awaited<ReturnType<typeof fetchCurrentEmploymentAssignment>>>(null)
  const [isLoadingAssignment, setIsLoadingAssignment] = useState(false)
  const [rows, setRows] = useState<EmployeeEntitlement[]>([])
  const [form, setForm] = useState<EmployeeEntitlementPayload>(blankForm)
  const [editing, setEditing] = useState<EmployeeEntitlement | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function reload() {
    const [nextEmployees, nextLeaveTypes, nextRows] = await Promise.all([
      fetchEmployees(),
      fetchLeaveTypes(),
      fetchEmployeeEntitlements(),
    ])
    const activeLeaveTypes = nextLeaveTypes.filter((type) => type.is_active && type.status === 'ACTIVE')
    setEmployees(nextEmployees)
    setLeaveTypes(activeLeaveTypes)
    setRows(nextRows)
    setForm((current) => ({
      ...current,
      employee_id: current.employee_id || nextEmployees[0]?.id || '',
    }))
  }

  useEffect(() => {
    Promise.all([fetchEmployees(), fetchLeaveTypes(), fetchEmployeeEntitlements()])
      .then(([nextEmployees, nextLeaveTypes, nextRows]) => {
        const activeLeaveTypes = nextLeaveTypes.filter((type) => type.is_active && type.status === 'ACTIVE')
        setEmployees(nextEmployees)
        setLeaveTypes(activeLeaveTypes)
        setRows(nextRows)
        setForm((current) => ({
          ...current,
          employee_id: current.employee_id || nextEmployees[0]?.id || '',
        }))
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Could not load entitlements.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!form.employee_id) {
      setAssignment(null)
      return
    }
    let isCurrent = true
    setIsLoadingAssignment(true)
    setAssignment(null)
    setError('')
    fetchCurrentEmploymentAssignment(form.employee_id)
      .then((currentAssignment) => {
        if (!isCurrent) return
        setAssignment(currentAssignment)
        if (!currentAssignment) {
          setError('The selected employee has no active employment assignment.')
        }
      })
      .catch((cause: unknown) => {
        if (isCurrent) setError(cause instanceof Error ? cause.message : 'Could not load the employee assignment.')
      })
      .finally(() => {
        if (isCurrent) setIsLoadingAssignment(false)
      })
    return () => {
      isCurrent = false
    }
  }, [form.employee_id])

  useEffect(() => {
    const refreshRows = () => {
      fetchEmployeeEntitlements()
        .then((nextRows) => {
          setRows(nextRows)
          setForm((current) => {
            if (!editing) return current
            const latest = nextRows.find((row) => row.id === editing.id)
            return latest
              ? { ...current, used_minutes: latest.used_minutes, available_minutes: latest.available_minutes }
              : current
          })
        })
        .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Could not refresh entitlements.'))
    }
    const interval = window.setInterval(refreshRows, 30_000)
    window.addEventListener('focus', refreshRows)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', refreshRows)
    }
  }, [editing])

  function setField<K extends keyof EmployeeEntitlementPayload>(key: K, value: EmployeeEntitlementPayload[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function resetForm() {
    setEditing(null)
    setForm({
      ...blankForm,
      employee_id: employees[0]?.id ?? '',
    })
  }

  function beginEdit(item: EmployeeEntitlement) {
    const { id, ...values } = item
    setEditing({ ...item, id })
    setForm(values)
    setError('')
    setSuccess('')
  }

  const today = getManilaDate()
  const availableLeaveTypes = leaveTypes.filter((type) =>
    assignment
    && type.company_id === assignment.company_id
    && type.is_active
    && type.status === 'ACTIVE'
    && type.effective_from <= today
    && (!type.effective_to || type.effective_to >= today),
  )
  const selectedLeaveType = leaveTypes.find((type) => type.id === form.leave_type_id)

  function selectedUnit(): LeaveUnitType {
    return selectedLeaveType?.unit_type
      ?? availableLeaveTypes[0]?.unit_type
      ?? leaveTypes[0]?.unit_type
      ?? 'DAYS'
  }

  const completedServiceMonths = assignment ? getCompletedServiceMonths(assignment.hire_date) : null
  const isServiceEligible = Boolean(
    selectedLeaveType
    && completedServiceMonths !== null
    && completedServiceMonths >= selectedLeaveType.minimum_service_months,
  )
  const canSave = Boolean(
    form.leave_type_id
    && selectedLeaveType
    && assignment
    && !isLoadingAssignment
    && isServiceEligible,
  )

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (!canSave) {
      setError('The employee must meet the leave type minimum service requirement before this entitlement can be granted.')
      return
    }
    setSaving(true)
    try {
      if (editing) await updateEmployeeEntitlement(editing.id, form)
      else await createEmployeeEntitlement(form)
      await reload()
      resetForm()
      setSuccess(editing ? 'Employee entitlement updated.' : 'Employee entitlement created.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this entitlement.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="employee-entitlements" onNavigate={onNavigate} onSignOut={logout} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-6 py-6">
        <header>
          <p className="text-sm font-semibold uppercase tracking-wide text-indigo-600">People</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Employee Entitlements</h1>
          <p className="mt-1 text-sm text-slate-500">Enter balances in the unit configured for each leave type (e.g. days).</p>
        </header>
        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {success && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</p>}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div><h2 className="text-lg font-bold text-slate-900">{editing ? 'Edit entitlement' : 'Add entitlement'}</h2><p className="text-sm text-slate-500">Available balance is calculated from credits minus used, reserved, expired, and converted balances.</p></div>
            {editing && <button type="button" onClick={resetForm} className="inline-flex items-center gap-1 text-sm font-semibold text-slate-600"><X className="h-4 w-4" /> Cancel</button>}
          </div>
          <form onSubmit={submit} className="grid gap-4 md:grid-cols-3">
            <label className="text-sm font-semibold text-slate-700">Employee
              <select className={inputClass} required disabled={Boolean(editing)} value={form.employee_id} onChange={(event) => {
                setForm((current) => ({ ...current, employee_id: event.target.value, leave_type_id: '', granted_minutes: 0 }))
              }}>
                <option value="">Select employee</option>{employees.map((employee) => <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">Leave code
              <select
                className={inputClass}
                required
                disabled={isLoadingAssignment || !assignment}
                value={form.leave_type_id}
                onChange={(event) => {
                  const leaveType = availableLeaveTypes.find((type) => type.id === event.target.value)
                  setForm((current) => ({
                    ...current,
                    leave_type_id: leaveType?.id ?? '',
                    granted_minutes: leaveType?.annual_entitlement_minutes ?? 0,
                  }))
                  setError('')
                }}
              >
                <option value="">Select leave code</option>
                {availableLeaveTypes.map((type) => <option key={type.id} value={type.id}>{type.leave_code} — {type.leave_name}</option>)}
              </select>
              {isLoadingAssignment && <p className="mt-1 text-xs font-normal text-slate-500">Loading employee assignment…</p>}
              {!isLoadingAssignment && form.employee_id && !assignment && <p className="mt-1 text-xs font-normal text-rose-700">No active employment assignment found for this employee.</p>}
            </label>
            <label className="text-sm font-semibold text-slate-700">Entitlement year
              <input className={inputClass} type="number" min={1900} max={2200} required value={form.entitlement_year} onChange={(event) => setField('entitlement_year', Number(event.target.value))} />
            </label>
            {([
              ['opening_minutes', 'Opening balance'],
              ['granted_minutes', 'Granted'],
              ['accrued_minutes', 'Accrued'],
              ['carryover_minutes', 'Carryover'],
              ['adjustment_minutes', 'Adjustment'],
              ['used_minutes', 'Used'],
              ['reserved_minutes', 'Reserved'],
              ['expired_minutes', 'Expired'],
              ['converted_minutes', 'Converted'],
            ] as const).map(([key, label]) => (
              <label key={key} className="text-sm font-semibold text-slate-700">{label} ({formatUnit(selectedUnit())})
                <input
                  className={inputClass}
                  type="number"
                  step={amountStep(selectedUnit())}
                  min={key === 'adjustment_minutes' || key === 'opening_minutes' ? undefined : 0}
                  required
                  value={Number(minutesToLeaveUnits(form[key], selectedUnit()).toFixed(3))}
                  onChange={(event) => setField(key, leaveUnitsToMinutes(Number(event.target.value), selectedUnit()))}
                />
              </label>
            ))}
            <div className="text-sm font-semibold text-slate-700">
              <span>Available balance (calculated)</span>
              <p className={`${inputClass} bg-slate-50 font-bold`}>{formatLeaveBalance(calculateAvailableMinutes(form), selectedUnit())}</p>
            </div>
            {selectedLeaveType && assignment && (
              <div className="text-sm font-semibold text-slate-700">
                <span>Service eligibility</span>
                <p className={`mt-1 rounded-lg px-3 py-2 text-sm ${
                  isServiceEligible ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
                }`}>
                  Hired {assignment.hire_date}: {completedServiceMonths} of {selectedLeaveType.minimum_service_months} months completed
                  {!isServiceEligible && ' — not eligible to grant'}
                </p>
              </div>
            )}
            <div className="md:col-span-3">
              <button disabled={saving || !employees.length || !canSave} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">{saving ? 'Saving…' : editing ? 'Save changes' : 'Create entitlement'}</button>
            </div>
          </form>
        </section>
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-5 py-4"><h2 className="text-lg font-bold text-slate-900">Employee balances</h2></div>
          {loading ? <p className="p-5 text-sm text-slate-500">Loading employee entitlements…</p> : rows.length === 0 ? <p className="p-5 text-sm text-slate-500">No employee entitlements configured.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-5 py-3">Employee</th><th className="px-5 py-3">Leave type</th><th className="px-5 py-3">Year</th><th className="px-5 py-3">Available</th><th className="px-5 py-3">Used</th><th className="px-5 py-3">Edit</th></tr></thead>
                <tbody className="divide-y divide-slate-100">{rows.map((item) => {
                  const employee = employees.find((candidate) => candidate.id === item.employee_id)
                  return <tr key={item.id}>
                    <td className="px-5 py-3">{employee ? employeeLabel(employee) : item.employee_id}</td>
                    <td className="px-5 py-3">{leaveTypes.find((type) => type.id === item.leave_type_id)?.leave_name ?? item.leave_type_id}</td>
                    <td className="px-5 py-3">{item.entitlement_year}</td>
                    <td className="px-5 py-3 font-semibold text-slate-900">
                      {formatLeaveBalance(item.available_minutes, leaveTypes.find((type) => type.id === item.leave_type_id)?.unit_type ?? 'DAYS')}
                    </td>
                    <td className="px-5 py-3">
                      {formatLeaveBalance(item.used_minutes, leaveTypes.find((type) => type.id === item.leave_type_id)?.unit_type ?? 'DAYS')}
                    </td>
                    <td className="px-5 py-3"><button type="button" onClick={() => beginEdit(item)} className="inline-flex items-center gap-1 font-semibold text-indigo-700 hover:text-indigo-900"><Pencil className="h-4 w-4" /> Edit</button></td>
                  </tr>
                })}</tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
