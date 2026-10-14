import { useEffect, useState } from 'react'
import { Pencil, Plus, X } from 'lucide-react'
import { fetchCurrentEmploymentAssignmentWithPrimaryLocation, getCompletedServiceMonths, getManilaDate } from '../../lib/employeeRelatedApi'
import {
  calculateAvailableMinutes,
  createEmployeeEntitlement,
  fetchEmployeeEntitlements,
  fetchLeaveTypes,
  formatLeaveBalance,
  leaveUnitsToMinutes,
  minutesToLeaveUnits,
  updateEmployeeEntitlement,
} from '../../lib/leaveApi'
import type { EmployeeEntitlement, EmployeeEntitlementPayload, LeaveType, LeaveUnitType } from '../../lib/leaveApi'
import type { Employee } from '../../types/employee'

interface Props {
  employee: Employee | null
}

const emptyEntitlement = (employeeId: string): EmployeeEntitlementPayload => ({
  employee_id: employeeId,
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
})

const inputClassName = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClassName = 'text-xs font-semibold text-slate-700'

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Could not load employee entitlements.'
}

function amountStep(unit: LeaveUnitType) {
  return unit === 'MINUTES' ? 1 : 0.001
}

export default function EmployeeEntitlementsPanel({ employee }: Props) {
  const employeeId = employee?.id ?? ''
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [entitlements, setEntitlements] = useState<EmployeeEntitlement[]>([])
  const [form, setForm] = useState<EmployeeEntitlementPayload>(() => emptyEntitlement(employee?.id ?? ''))
  const [assignment, setAssignment] = useState<Awaited<ReturnType<typeof fetchCurrentEmploymentAssignmentWithPrimaryLocation>>>(null)
  const [editing, setEditing] = useState<EmployeeEntitlement | null>(null)
  const [isLoading, setIsLoading] = useState(Boolean(employee))
  const [isSaving, setIsSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    if (!employeeId) {
      setAssignment(null)
      setLeaveTypes([])
      setEntitlements([])
      setForm(emptyEntitlement(''))
      setIsLoading(false)
      return
    }
    let isCurrent = true
    setIsLoading(true)
    setEditing(null)
    setAssignment(null)
    setLeaveTypes([])
    setEntitlements([])
    setForm(emptyEntitlement(employeeId))
    setErrorMessage('')
    setSuccessMessage('')
    const refreshEntitlements = async () => {
      try {
        const rows = await fetchEmployeeEntitlements(employeeId)
        if (isCurrent) setEntitlements(rows)
      } catch (error) {
        if (isCurrent) setErrorMessage(errorText(error))
      }
    }
    Promise.all([fetchCurrentEmploymentAssignmentWithPrimaryLocation(employeeId), fetchEmployeeEntitlements(employeeId)])
      .then(async ([currentAssignment, rows]) => {
        if (!isCurrent) return
        setAssignment(currentAssignment)
        setEntitlements(rows)
        if (!currentAssignment) {
          setErrorMessage('This employee has no active employment assignment.')
          return
        }
        const types = await fetchLeaveTypes({ companyId: currentAssignment.company_id })
        if (!isCurrent) return
        setLeaveTypes(types.filter((type) => type.is_active && type.status === 'ACTIVE'))
        setEntitlements(rows)
        setForm((current) => ({
          ...current,
          employee_id: employeeId,
        }))
      })
      .catch((error: unknown) => {
        if (isCurrent) setErrorMessage(errorText(error))
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })
    const refreshTimer = window.setInterval(() => void refreshEntitlements(), 30 * 1000)
    window.addEventListener('focus', refreshEntitlements)
    return () => {
      isCurrent = false
      window.clearInterval(refreshTimer)
      window.removeEventListener('focus', refreshEntitlements)
    }
  }, [employeeId])

  if (!employee) {
    return (
      <div className="space-y-4">
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Employee entitlements</h3>
        <p className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Create the employee record first, then reopen it to configure leave entitlements.
        </p>
      </div>
    )
  }

  function setField<K extends keyof EmployeeEntitlementPayload>(key: K, value: EmployeeEntitlementPayload[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function resetForm() {
    setEditing(null)
    setForm({
      ...emptyEntitlement(employeeId),
    })
  }

  function beginEdit(item: EmployeeEntitlement) {
    const { id, ...values } = item
    void id
    setEditing(item)
    setForm(values)
    setErrorMessage('')
    setSuccessMessage('')
  }

  const today = getManilaDate()
  const availableLeaveTypes = leaveTypes.filter((type) =>
    type.is_active
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
    && isServiceEligible,
  )

  async function submit() {
    setErrorMessage('')
    setSuccessMessage('')
    if (!canSave) {
      setErrorMessage('The employee must meet the leave type minimum service requirement before this entitlement can be granted.')
      return
    }
    setIsSaving(true)
    try {
      if (editing) {
        await updateEmployeeEntitlement(editing.id, form)
      } else {
        await createEmployeeEntitlement(form)
      }
      setEntitlements(await fetchEmployeeEntitlements(employeeId))
      resetForm()
      setSuccessMessage(editing ? 'Entitlement updated.' : 'Entitlement added.')
    } catch (error) {
      setErrorMessage(errorText(error))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Employee entitlements</h3>
        <p className="mt-1 text-xs text-slate-500">Leave balances for {employee.employee_no} based on the unit configured for each leave type.</p>
      </div>
      {errorMessage && <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
      {successMessage && <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{successMessage}</p>}

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Leave type</th>
              <th className="px-3 py-2">Year</th>
              <th className="px-3 py-2">Available</th>
              <th className="px-3 py-2">Used</th>
              <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && <tr><td colSpan={5} className="px-3 py-3 text-slate-500">Loading entitlements…</td></tr>}
            {!isLoading && entitlements.length === 0 && <tr><td colSpan={5} className="px-3 py-3 text-slate-500">No leave entitlements for this employee yet.</td></tr>}
            {entitlements.map((item) => (
              <tr key={item.id} className={editing?.id === item.id ? 'bg-indigo-50' : ''}>
                <td className="px-3 py-2 font-semibold text-slate-900">
                  {leaveTypes.find((type) => type.id === item.leave_type_id)?.leave_name ?? item.leave_type_id}
                </td>
                <td className="px-3 py-2">{item.entitlement_year}</td>
                <td className="px-3 py-2">{formatLeaveBalance(
                  item.available_minutes,
                  leaveTypes.find((type) => type.id === item.leave_type_id)?.unit_type ?? 'DAYS',
                )}</td>
                <td className="px-3 py-2">{formatLeaveBalance(
                  item.used_minutes,
                  leaveTypes.find((type) => type.id === item.leave_type_id)?.unit_type ?? 'DAYS',
                )}</td>
                <td className="px-3 py-2 text-right">
                  <button type="button" onClick={() => beginEdit(item)} aria-label="Edit entitlement" className="rounded-md p-1.5 text-slate-500 hover:bg-indigo-50 hover:text-indigo-700">
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section
        className="rounded-lg border border-slate-200 bg-slate-50/60 p-3"
        onKeyDown={(event) => {
          if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault()
        }}
      >
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-bold text-slate-700">{editing ? 'Edit entitlement' : 'Add entitlement'}</h4>
          {editing && <button type="button" onClick={resetForm} className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600"><X className="h-3.5 w-3.5" /> Cancel</button>}
        </div>
        <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClassName}>Leave code
            <select
              className={inputClassName}
              required
              disabled={isLoading || !assignment}
              value={form.leave_type_id}
              onChange={(event) => {
                const leaveType = availableLeaveTypes.find((type) => type.id === event.target.value)
                setForm((current) => ({
                  ...current,
                  leave_type_id: leaveType?.id ?? '',
                  granted_minutes: leaveType?.annual_entitlement_minutes ?? 0,
                }))
                setErrorMessage('')
              }}
            >
              <option value="">Select leave code</option>
              {availableLeaveTypes.map((type) => <option key={type.id} value={type.id}>{type.leave_code} — {type.leave_name}</option>)}
            </select>
            {isLoading && <p className="mt-1 font-normal text-slate-500">Loading employee assignment…</p>}
            {!isLoading && !assignment && <p className="mt-1 font-normal text-rose-700">No active employment assignment found for this employee.</p>}
          </label>
          <label className={labelClassName}>Entitlement year
            <input className={inputClassName} type="number" min={1900} max={2200} required value={form.entitlement_year} onChange={(event) => setField('entitlement_year', Number(event.target.value))} />
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
            <label key={key} className={labelClassName}>{label} ({selectedUnit().toLowerCase()})
              <input
                className={inputClassName}
                type="number"
                step={amountStep(selectedUnit())}
                min={key === 'opening_minutes' || key === 'adjustment_minutes' ? undefined : 0}
                required
                value={Number(minutesToLeaveUnits(form[key], selectedUnit()).toFixed(3))}
                onChange={(event) => setField(key, leaveUnitsToMinutes(Number(event.target.value), selectedUnit()))}
              />
            </label>
          ))}
          <div className={labelClassName}>
            <span>Available balance (calculated)</span>
            <p className={`${inputClassName} bg-slate-50 font-bold`}>{formatLeaveBalance(calculateAvailableMinutes(form), selectedUnit())}</p>
          </div>
          {selectedLeaveType && assignment && (
            <div className={labelClassName}>
              <span>Service eligibility</span>
              <p className={`mt-1 rounded-lg px-3 py-2 text-xs ${
                isServiceEligible ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
              }`}>
                Hired {assignment.hire_date}: {completedServiceMonths} of {selectedLeaveType.minimum_service_months} months completed
                {!isServiceEligible && ' — not eligible to grant'}
              </p>
            </div>
          )}
          <div className="flex justify-end sm:col-span-2 lg:col-span-3">
            <button type="button" onClick={submit} disabled={isSaving || !leaveTypes.length || !canSave} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60">
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              {isSaving ? 'Saving…' : editing ? 'Save changes' : 'Add entitlement'}
            </button>
          </div>
        </div>
        {!isLoading && leaveTypes.length === 0 && <p className="mt-2 text-xs text-amber-700">Configure an active leave type before adding an employee entitlement.</p>}
      </section>
    </div>
  )
}
