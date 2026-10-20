import { useEffect, useState, type FormEvent } from 'react'
import { Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import type { PayrollUseCases } from '../application/useCases'
import type {
  BenefitCategory,
  BenefitTaxTreatment,
  BenefitPostingSchedule,
  BenefitType,
  BenefitTypeInput,
  CutoffBenefit,
  EmployeeBenefitEntitlement,
  EmployeeBenefitEntitlementInput,
  EmployeeBenefitDeduction,
  EmployeeBenefitDeductionInput,
  EmployeeYtdTaxBalance,
  PayrollCutoffOption,
  PayrollEmployeeOption,
} from '../domain/payroll'

interface Props {
  payrollGroupId: string
  useCases: PayrollUseCases
  mode?: 'all' | 'types' | 'deductions' | 'entries' | 'payroll-deductions'
}

const categories: { value: BenefitCategory; label: string }[] = [
  { value: 'CASH_ALLOWANCE', label: 'Recurring cash allowance' },
  { value: 'ONE_TIME_BONUS', label: 'One-time bonus or incentive' },
  { value: 'REIMBURSEMENT', label: 'Expense reimbursement' },
  { value: 'EMPLOYER_PAID_INSURANCE', label: 'Employer-paid HMO or insurance' },
  { value: 'NON_CASH', label: 'Other non-cash benefit' },
  { value: 'EMPLOYEE_DEDUCTION', label: 'Employee-paid benefit deduction' },
]

const treatments: { value: BenefitTaxTreatment; label: string }[] = [
  { value: 'TAXABLE', label: 'Taxable' },
  { value: 'EXEMPT', label: 'Tax-exempt' },
  { value: 'EXEMPT_LIMITED', label: 'Exempt subject to annual limit' },
]

const initialType: BenefitTypeInput = {
  payrollGroupId: '',
  code: '',
  name: '',
  category: 'CASH_ALLOWANCE',
  taxTreatment: 'TAXABLE',
  attendanceBased: false,
  deductForLate: false,
  deductForUndertime: false,
  postingSchedule: 'EVERY_CUTOFF',
}

function emptyTypeDraft(payrollGroupId: string, mode: Props['mode']): BenefitTypeInput {
  return {
    ...initialType,
    payrollGroupId,
    category: mode === 'deductions' ? 'EMPLOYEE_DEDUCTION' : initialType.category,
    taxTreatment: mode === 'deductions' ? 'EXEMPT' : initialType.taxTreatment,
  }
}

const deductionSchedules = [
  { value: 'FIRST_HALF', label: 'First half-month payroll' },
  { value: 'SECOND_HALF', label: 'Second half-month payroll' },
  { value: 'EVERY_CUTOFF', label: 'Every cutoff' },
] as const

const postingSchedules: { value: BenefitPostingSchedule; label: string }[] = [
  { value: 'FIRST_HALF', label: 'First half-month payroll' },
  { value: 'SECOND_HALF', label: 'Second half-month payroll' },
  { value: 'EVERY_CUTOFF', label: 'Every cutoff' },
]

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function formatMoney(value: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'PHP' }).format(value)
}

export default function BenefitsManagement({
  payrollGroupId,
  useCases,
  mode = 'all',
}: Props) {
  const [types, setTypes] = useState<BenefitType[]>([])
  const [cutoffs, setCutoffs] = useState<PayrollCutoffOption[]>([])
  const [employees, setEmployees] = useState<PayrollEmployeeOption[]>([])
  const [entries, setEntries] = useState<CutoffBenefit[]>([])
  const [employeeDeductions, setEmployeeDeductions] = useState<EmployeeBenefitDeduction[]>([])
  const [employeeEntitlements, setEmployeeEntitlements] = useState<EmployeeBenefitEntitlement[]>([])
  const [selectedCutoffId, setSelectedCutoffId] = useState('')
  const [typeDraft, setTypeDraft] = useState<BenefitTypeInput>(() => emptyTypeDraft(payrollGroupId, mode))
  const [editingTypeId, setEditingTypeId] = useState('')
  const [deductionDraft, setDeductionDraft] = useState({
    employeeId: '',
    benefitTypeId: '',
    amountPerOccurrence: '',
    schedule: 'FIRST_HALF' as EmployeeBenefitDeductionInput['schedule'],
    effectiveFrom: new Date().toISOString().slice(0, 10),
    effectiveTo: '',
  })
  const [editingDeductionId, setEditingDeductionId] = useState('')
  const [entitlementDraft, setEntitlementDraft] = useState({
    employeeId: '',
    benefitTypeId: '',
    amountPerOccurrence: '',
    effectiveFrom: new Date().toISOString().slice(0, 10),
    effectiveTo: '',
  })
  const [editingEntitlementId, setEditingEntitlementId] = useState('')
  const [entryDraft, setEntryDraft] = useState({ employeeId: '', benefitTypeId: '', amount: '', notes: '' })
  const [editingEntryId, setEditingEntryId] = useState('')
  const [ytdEmployeeId, setYtdEmployeeId] = useState('')
  const [ytdDraft, setYtdDraft] = useState({ taxableIncome: '', taxWithheld: '', exemptLimitedBenefits: '' })
  const [ytdFound, setYtdFound] = useState(false)
  const [loadingYtd, setLoadingYtd] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const selectedCutoff = cutoffs.find((cutoff) => cutoff.id === selectedCutoffId)
  const taxYear = selectedCutoff ? Number(selectedCutoff.periodStart.slice(0, 4)) : new Date().getFullYear()
  const canEditEntries = Boolean(selectedCutoff && !selectedCutoff.locked)
  const activeTypes = types.filter((benefit) => (
    benefit.isActive && benefit.category !== 'EMPLOYEE_DEDUCTION'
  ))
  const deductionTypes = types.filter((benefit) => benefit.category === 'EMPLOYEE_DEDUCTION')
  const managedTypes = mode === 'deductions' ? deductionTypes : types.filter(
    (benefit) => benefit.category !== 'EMPLOYEE_DEDUCTION',
  )
  const deductionTypesForForm = deductionTypes.filter((benefit) => (
    benefit.isActive || benefit.id === deductionDraft.benefitTypeId
  ))
  const entryTypes = activeTypes.filter(
    (benefit) => benefit.isActive || benefit.id === entryDraft.benefitTypeId,
  )
  const entitlementTypesForForm = activeTypes.filter((benefit) => (
    benefit.id === entitlementDraft.benefitTypeId || benefit.isActive
  ))
  const selectedEntryType = entryTypes.find((benefit) => benefit.id === entryDraft.benefitTypeId)
  const selectedEntryEmployee = employees.find((employee) => employee.id === entryDraft.employeeId)
  const visibleCutoffEntries = entries.filter(
    (entry) => entry.employeeId === entryDraft.employeeId && entry.category !== 'EMPLOYEE_DEDUCTION',
  )
  const selectedDeductionEmployee = employees.find(
    (employee) => employee.id === deductionDraft.employeeId,
  )
  const visibleEmployeeDeductions = employeeDeductions.filter(
    (deduction) => deduction.employeeId === deductionDraft.employeeId,
  )
  const visibleEmployeeEntitlements = employeeEntitlements.filter(
    (entitlement) => entitlement.employeeId === entitlementDraft.employeeId,
  )
  const selectedEntitlementType = entitlementTypesForForm.find(
    (benefit) => benefit.id === entitlementDraft.benefitTypeId,
  )

  useEffect(() => {
    setTypeDraft(emptyTypeDraft(payrollGroupId, mode))
  }, [mode, payrollGroupId])

  useEffect(() => {
    let current = true
    setLoading(true)
    Promise.all([
      useCases.listBenefitTypes(payrollGroupId),
      mode === 'all' || mode === 'entries'
        ? useCases.listCutoffs(payrollGroupId)
        : Promise.resolve([]),
      useCases.listEmployees(),
      mode === 'types' ? Promise.resolve([]) : useCases.listEmployeeBenefitDeductions(payrollGroupId),
      mode === 'deductions' || mode === 'payroll-deductions'
        ? Promise.resolve([])
        : useCases.listEmployeeBenefitEntitlements(payrollGroupId),
    ])
      .then(([nextTypes, nextCutoffs, nextEmployees, nextDeductions, nextEntitlements]) => {
        if (!current) return
        setTypes(nextTypes)
        setCutoffs(nextCutoffs)
        setEmployees(nextEmployees.filter((employee) => employee.isActive))
        setEmployeeDeductions(nextDeductions)
        setEmployeeEntitlements(nextEntitlements)
        setSelectedCutoffId((existing) => nextCutoffs.some((cutoff) => cutoff.id === existing)
          ? existing
          : nextCutoffs.find((cutoff) => !cutoff.locked)?.id ?? nextCutoffs[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load benefit setup.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => { current = false }
  }, [mode, payrollGroupId, refreshKey, useCases])

  useEffect(() => {
    let current = true
    setEntries([])
    if ((mode !== 'all' && mode !== 'entries') || !selectedCutoffId) return () => { current = false }
    useCases.listCutoffBenefits(selectedCutoffId)
      .then((nextEntries) => {
        if (current) setEntries(nextEntries)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load cutoff benefits.')
      })
    return () => { current = false }
  }, [mode, selectedCutoffId, refreshKey, useCases])

  useEffect(() => {
    let current = true
    setYtdFound(false)
    setYtdDraft({ taxableIncome: '', taxWithheld: '', exemptLimitedBenefits: '' })
    if (!ytdEmployeeId) return () => { current = false }
    setLoadingYtd(true)
    useCases.getEmployeeYtdTaxBalance(ytdEmployeeId, taxYear)
      .then((balance) => {
        if (!current) return
        setYtdFound(balance !== null)
        if (balance) {
          setYtdDraft({
            taxableIncome: String(balance.taxableIncome),
            taxWithheld: String(balance.taxWithheld),
            exemptLimitedBenefits: String(balance.exemptLimitedBenefits),
          })
        }
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load opening balances.')
      })
      .finally(() => {
        if (current) setLoadingYtd(false)
      })
    return () => { current = false }
  }, [taxYear, ytdEmployeeId, useCases])

  function resetType() {
    setTypeDraft(emptyTypeDraft(payrollGroupId, mode))
    setEditingTypeId('')
  }

  function resetDeduction() {
    const employeeId = deductionDraft.employeeId
    setDeductionDraft({
      employeeId,
      benefitTypeId: '',
      amountPerOccurrence: '',
      schedule: 'FIRST_HALF',
      effectiveFrom: new Date().toISOString().slice(0, 10),
      effectiveTo: '',
    })
    setEditingDeductionId('')
  }

  function resetEntitlement(preserveEmployee = false) {
    setEntitlementDraft((current) => ({
      employeeId: preserveEmployee ? current.employeeId : '',
      benefitTypeId: '',
      amountPerOccurrence: '',
      effectiveFrom: new Date().toISOString().slice(0, 10),
      effectiveTo: '',
    }))
    setEditingEntitlementId('')
  }

  function resetEntry(preserveEmployee = false) {
    setEntryDraft((current) => ({
      employeeId: preserveEmployee ? current.employeeId : '',
      benefitTypeId: '',
      amount: '',
      notes: '',
    }))
    setEditingEntryId('')
  }

  function startTypeEdit(benefit: BenefitType) {
    setEditingTypeId(benefit.id)
    setTypeDraft({
      payrollGroupId,
      code: benefit.code,
      name: benefit.name,
      category: benefit.category,
      taxTreatment: benefit.taxTreatment,
      attendanceBased: benefit.attendanceBased,
      deductForLate: benefit.deductForLate,
      deductForUndertime: benefit.deductForUndertime,
      postingSchedule: benefit.postingSchedule,
    })
    setError('')
  }

  async function saveType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      if (editingTypeId) await useCases.updateBenefitType(editingTypeId, typeDraft)
      else await useCases.createBenefitType(typeDraft)
      resetType()
      setNotice(editingTypeId ? 'Benefit type updated.' : 'Benefit type created.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the benefit type.')
    } finally {
      setSaving(false)
    }
  }

  async function toggleType(benefit: BenefitType) {
    setError('')
    setNotice('')
    try {
      await useCases.setBenefitTypeActive(benefit.id, !benefit.isActive)
      setNotice(benefit.isActive ? 'Benefit type deactivated.' : 'Benefit type activated.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update benefit type status.')
    }
  }

  function startDeductionEdit(deduction: EmployeeBenefitDeduction) {
    setEditingDeductionId(deduction.id)
    setDeductionDraft({
      employeeId: deduction.employeeId,
      benefitTypeId: deduction.benefitTypeId,
      amountPerOccurrence: String(deduction.amountPerOccurrence),
      schedule: deduction.schedule,
      effectiveFrom: deduction.effectiveFrom,
      effectiveTo: deduction.effectiveTo ?? '',
    })
    setError('')
  }

  async function saveDeduction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input: EmployeeBenefitDeductionInput = {
      employeeId: deductionDraft.employeeId,
      benefitTypeId: deductionDraft.benefitTypeId,
      amountPerOccurrence: Number(deductionDraft.amountPerOccurrence),
      schedule: deductionDraft.schedule,
      effectiveFrom: deductionDraft.effectiveFrom,
      effectiveTo: deductionDraft.effectiveTo || null,
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      if (editingDeductionId) {
        await useCases.updateEmployeeBenefitDeduction(editingDeductionId, input)
      } else {
        await useCases.createEmployeeBenefitDeduction(input)
      }
      resetDeduction()
      setNotice(editingDeductionId ? 'Recurring deduction updated.' : 'Recurring deduction created.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the recurring deduction.')
    } finally {
      setSaving(false)
    }
  }

  async function toggleDeduction(deduction: EmployeeBenefitDeduction) {
    setError('')
    setNotice('')
    try {
      await useCases.setEmployeeBenefitDeductionActive(deduction.id, !deduction.isActive)
      setNotice(deduction.isActive ? 'Recurring deduction deactivated.' : 'Recurring deduction activated.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update the recurring deduction.')
    }
  }

  function startEntitlementEdit(entitlement: EmployeeBenefitEntitlement) {
    setEditingEntitlementId(entitlement.id)
    setEntitlementDraft({
      employeeId: entitlement.employeeId,
      benefitTypeId: entitlement.benefitTypeId,
      amountPerOccurrence: String(entitlement.amountPerOccurrence),
      effectiveFrom: entitlement.effectiveFrom,
      effectiveTo: entitlement.effectiveTo ?? '',
    })
    setError('')
  }

  async function saveEntitlement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input: EmployeeBenefitEntitlementInput = {
      employeeId: entitlementDraft.employeeId,
      benefitTypeId: entitlementDraft.benefitTypeId,
      amountPerOccurrence: Number(entitlementDraft.amountPerOccurrence),
      effectiveFrom: entitlementDraft.effectiveFrom,
      effectiveTo: entitlementDraft.effectiveTo || null,
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      if (editingEntitlementId) {
        await useCases.updateEmployeeBenefitEntitlement(editingEntitlementId, input)
      } else {
        await useCases.createEmployeeBenefitEntitlement(input)
      }
      resetEntitlement(true)
      setNotice(editingEntitlementId ? 'Employee benefit entitlement updated.' : 'Employee benefit entitlement saved.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the employee benefit entitlement.')
    } finally {
      setSaving(false)
    }
  }

  async function toggleEntitlement(entitlement: EmployeeBenefitEntitlement) {
    setError('')
    setNotice('')
    try {
      await useCases.setEmployeeBenefitEntitlementActive(entitlement.id, !entitlement.isActive)
      setNotice(entitlement.isActive ? 'Employee benefit entitlement deactivated.' : 'Employee benefit entitlement activated.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update the employee benefit entitlement.')
    }
  }

  function startEntryEdit(entry: CutoffBenefit) {
    setEditingEntryId(entry.id)
    setEntryDraft({
      employeeId: entry.employeeId,
      benefitTypeId: entry.benefitTypeId,
      amount: String(entry.amount),
      notes: entry.notes ?? '',
    })
  }

  async function saveEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedCutoffId) return
    setSaving(true)
    setError('')
    setNotice('')
    const input = {
      cutoffId: selectedCutoffId,
      employeeId: entryDraft.employeeId,
      benefitTypeId: entryDraft.benefitTypeId,
      amount: Number(entryDraft.amount),
      notes: entryDraft.notes.trim() || null,
    }
    try {
      if (editingEntryId) await useCases.updateCutoffBenefit(editingEntryId, input)
      else await useCases.createCutoffBenefit(input)
      resetEntry(true)
      setNotice(editingEntryId ? 'Cutoff benefit updated.' : 'Cutoff benefit recorded.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the cutoff benefit.')
    } finally {
      setSaving(false)
    }
  }

  async function deleteEntry(entry: CutoffBenefit) {
    if (!window.confirm(`Delete ${entry.benefitName} for this cutoff?`)) return
    setError('')
    setNotice('')
    try {
      await useCases.deleteCutoffBenefit(entry.id)
      setNotice('Cutoff benefit deleted.')
      setRefreshKey((key) => key + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete the cutoff benefit.')
    }
  }

  async function saveYtdBalance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const balance: EmployeeYtdTaxBalance = {
      employeeId: ytdEmployeeId,
      taxYear,
      taxableIncome: Number(ytdDraft.taxableIncome),
      taxWithheld: Number(ytdDraft.taxWithheld),
      exemptLimitedBenefits: Number(ytdDraft.exemptLimitedBenefits),
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await useCases.saveEmployeeYtdTaxBalance(balance)
      setYtdFound(true)
      setNotice(`Tax-year opening balances saved for ${taxYear}.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save opening balances.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
      {loading && <p role="status" className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">Loading benefit setup…</p>}

      {(mode === 'all' || mode === 'types' || mode === 'deductions') && <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">{mode === 'deductions' ? 'Deduction types' : 'Benefit types'}</h2>
            <p className="mt-1 text-sm text-slate-500">
              {mode === 'deductions'
                ? 'Configure non-statutory employee deductions, such as loans, cash advances, and other recurring deductions.'
                : 'Configure benefit category and tax treatment for this payroll group.'}
            </p>
          </div>
          <button type="button" onClick={resetType} className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 px-3 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50">
            <Plus className="h-4 w-4" aria-hidden="true" /> New type
          </button>
        </div>

        <form onSubmit={(event) => void saveType(event)} className="mb-5 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs font-semibold text-slate-600">
            Code
            <input required maxLength={30} value={typeDraft.code} onChange={(event) => setTypeDraft({ ...typeDraft, code: event.target.value.toUpperCase() })} className={inputClass} placeholder="MEAL" />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Benefit name
            <input required maxLength={120} value={typeDraft.name} onChange={(event) => setTypeDraft({ ...typeDraft, name: event.target.value })} className={inputClass} placeholder="Meal allowance" />
          </label>
          {mode !== 'deductions' && <label className="text-xs font-semibold text-slate-600">
            Category
            <select value={typeDraft.category} onChange={(event) => {
              const category = event.target.value as BenefitCategory
              setTypeDraft({
                ...typeDraft,
                category,
                taxTreatment: category === 'EMPLOYEE_DEDUCTION' ? 'EXEMPT' : typeDraft.taxTreatment,
                attendanceBased: category === 'EMPLOYEE_DEDUCTION' ? false : typeDraft.attendanceBased,
                deductForLate: category === 'EMPLOYEE_DEDUCTION' ? false : typeDraft.deductForLate,
                deductForUndertime: category === 'EMPLOYEE_DEDUCTION' ? false : typeDraft.deductForUndertime,
              })
            }} className={inputClass}>
              {categories
                .filter((category) => category.value !== 'EMPLOYEE_DEDUCTION')
                .map((category) => <option key={category.value} value={category.value}>{category.label}</option>)}
            </select>
          </label>}
          {mode === 'deductions' ? (
            <p className="text-xs font-semibold text-slate-600">
              Deduction classification
              <span className={`${inputClass} block`}>Non-statutory employee deduction · Tax-exempt</span>
            </p>
          ) : <label className="text-xs font-semibold text-slate-600">
            Tax treatment
            <select
              required
              disabled={typeDraft.category === 'EMPLOYEE_DEDUCTION'}
              value={typeDraft.taxTreatment}
              onChange={(event) => setTypeDraft({ ...typeDraft, taxTreatment: event.target.value as BenefitTaxTreatment })}
              className={inputClass}
            >
              {treatments.map((treatment) => <option key={treatment.value} value={treatment.value}>{treatment.label}</option>)}
            </select>
          </label>}
          {mode !== 'deductions' && (
            <label className="text-xs font-semibold text-slate-600">
              Payroll schedule
              <select
                required
                value={typeDraft.postingSchedule}
                onChange={(event) => setTypeDraft({
                  ...typeDraft,
                  postingSchedule: event.target.value as BenefitPostingSchedule,
                })}
                className={inputClass}
              >
                {postingSchedules.map((schedule) => (
                  <option key={schedule.value} value={schedule.value}>{schedule.label}</option>
                ))}
              </select>
            </label>
          )}
          {mode !== 'deductions' && <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 sm:col-span-2">
            <input
              type="checkbox"
              checked={typeDraft.attendanceBased}
              disabled={typeDraft.category === 'EMPLOYEE_DEDUCTION'}
              onChange={(event) => setTypeDraft({
                ...typeDraft,
                attendanceBased: event.target.checked,
                deductForLate: event.target.checked && typeDraft.deductForLate,
                deductForUndertime: event.target.checked && typeDraft.deductForUndertime,
              })}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            Calculate benefit from paid days and attendance
          </label>}
          {mode !== 'deductions' && typeDraft.attendanceBased && typeDraft.category !== 'EMPLOYEE_DEDUCTION' && (
            <>
              <p className="text-xs leading-5 text-slate-500 sm:col-span-2 lg:col-span-4">
                The cutoff amount is prorated by paid days ÷ scheduled days. If enabled, late and undertime are deducted at cutoff amount ÷ total required work minutes from the assigned schedule templates, multiplied by the applicable minutes. Paid days include approved paid leave.
              </p>
              <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={typeDraft.deductForLate}
                  onChange={(event) => setTypeDraft({ ...typeDraft, deductForLate: event.target.checked })}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                Deduct for late minutes
              </label>
              <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={typeDraft.deductForUndertime}
                  onChange={(event) => setTypeDraft({ ...typeDraft, deductForUndertime: event.target.checked })}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                Deduct for undertime minutes
              </label>
            </>
          )}
          <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
            <button disabled={saving} type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
              <Save className="h-4 w-4" aria-hidden="true" /> {saving ? 'Saving…' : editingTypeId ? 'Update type' : 'Save type'}
            </button>
            {editingTypeId && <button type="button" onClick={resetType} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"><X className="h-4 w-4" aria-hidden="true" /> Cancel</button>}
          </div>
        </form>

        {managedTypes.length === 0 ? <p className="text-sm text-slate-500">No {mode === 'deductions' ? 'deduction' : 'benefit'} types defined for this payroll group.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[42rem] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Code / name</th><th className="px-3 py-2">Category</th><th className="px-3 py-2">Tax treatment</th><th className="px-3 py-2">Payroll schedule</th><th className="px-3 py-2">Attendance rule</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {managedTypes.map((benefit) => (
                  <tr key={benefit.id}>
                    <td className="px-3 py-3"><span className="font-semibold text-slate-900">{benefit.code}</span><span className="block text-xs text-slate-500">{benefit.name}</span></td>
                    <td className="px-3 py-3 text-xs text-slate-700">{categories.find((item) => item.value === benefit.category)?.label}</td>
                    <td className="px-3 py-3 text-xs text-slate-700">{treatments.find((item) => item.value === benefit.taxTreatment)?.label}</td>
                    <td className="px-3 py-3 text-xs text-slate-700">{postingSchedules.find((item) => item.value === benefit.postingSchedule)?.label}</td>
                    <td className="px-3 py-3 text-xs text-slate-700">
                      {benefit.attendanceBased
                        ? `Paid days; late deduction ${benefit.deductForLate ? 'on' : 'off'}; undertime deduction ${benefit.deductForUndertime ? 'on' : 'off'}`
                        : 'Manual amount'}
                    </td>
                    <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${benefit.isActive ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{benefit.isActive ? 'ACTIVE' : 'INACTIVE'}</span></td>
                    <td className="px-3 py-3">
                      <div className="flex gap-1.5">
                        <button type="button" aria-label={`Edit ${benefit.name}`} onClick={() => startTypeEdit(benefit)} className="rounded border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50"><Pencil className="h-4 w-4" aria-hidden="true" /></button>
                        <button type="button" onClick={() => void toggleType(benefit)} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">{benefit.isActive ? 'Deactivate' : 'Activate'}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {(mode === 'all' || mode === 'types') && <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Employee benefit entitlements</h2>
            <p className="mt-1 text-sm text-slate-500">
              Active entitlements are automatically included when payroll is calculated according to the benefit type’s posting schedule. A manual cutoff entry for the same employee and benefit takes precedence for that cutoff.
            </p>
          </div>
          <button
            type="button"
            onClick={() => resetEntitlement(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 px-3 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50"
          >
            <Plus className="h-4 w-4" aria-hidden="true" /> New entitlement
          </button>
        </div>
        <form onSubmit={(event) => void saveEntitlement(event)} className="grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-xs font-semibold text-slate-600">
            Employee
            <select required value={entitlementDraft.employeeId} onChange={(event) => setEntitlementDraft({ ...entitlementDraft, employeeId: event.target.value })} className={inputClass}>
              <option value="">Select employee</option>
              {employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.employeeNo} — {employee.fullName}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Benefit type
            <select required value={entitlementDraft.benefitTypeId} onChange={(event) => setEntitlementDraft({ ...entitlementDraft, benefitTypeId: event.target.value })} className={inputClass}>
              <option value="">Select benefit type</option>
              {entitlementTypesForForm.map((benefit) => <option key={benefit.id} value={benefit.id}>{benefit.code} — {benefit.name}</option>)}
            </select>
            {selectedEntitlementType && (
              <span className="mt-1 block font-normal text-slate-500">
                Schedule: {postingSchedules.find((schedule) => schedule.value === selectedEntitlementType.postingSchedule)?.label}
              </span>
            )}
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Amount per posting (PHP)
            <input required type="number" min="0.01" step="0.01" value={entitlementDraft.amountPerOccurrence} onChange={(event) => setEntitlementDraft({ ...entitlementDraft, amountPerOccurrence: event.target.value })} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Effective from
            <input required type="date" value={entitlementDraft.effectiveFrom} onChange={(event) => setEntitlementDraft({ ...entitlementDraft, effectiveFrom: event.target.value })} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Effective to (optional)
            <input type="date" value={entitlementDraft.effectiveTo} onChange={(event) => setEntitlementDraft({ ...entitlementDraft, effectiveTo: event.target.value })} className={inputClass} />
          </label>
          <div className="flex items-end gap-2">
            <button disabled={saving || entitlementTypesForForm.length === 0} type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
              <Save className="h-4 w-4" aria-hidden="true" /> {saving ? 'Saving…' : editingEntitlementId ? 'Update entitlement' : 'Save entitlement'}
            </button>
            {editingEntitlementId && <button type="button" onClick={() => resetEntitlement(true)} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"><X className="h-4 w-4" aria-hidden="true" /> Cancel</button>}
          </div>
        </form>
        {!entitlementDraft.employeeId ? (
          <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">Select an employee above to view their benefit entitlements.</p>
        ) : visibleEmployeeEntitlements.length === 0 ? (
          <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No benefit entitlements found for {employees.find((employee) => employee.id === entitlementDraft.employeeId)?.fullName ?? 'the selected employee'}.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[54rem] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Employee</th><th className="px-3 py-2">Benefit</th><th className="px-3 py-2">Amount / schedule</th><th className="px-3 py-2">Effective period</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleEmployeeEntitlements.map((entitlement) => {
                  const employee = employees.find((person) => person.id === entitlement.employeeId)
                  const benefitType = types.find((benefit) => benefit.id === entitlement.benefitTypeId)
                  const scheduleLabel = postingSchedules.find((schedule) => schedule.value === benefitType?.postingSchedule)?.label ?? 'Unavailable'
                  return (
                    <tr key={entitlement.id}>
                      <td className="px-3 py-3"><span className="font-medium text-slate-900">{employee?.fullName ?? 'Employee record'}</span><span className="block text-xs text-slate-500">{employee?.employeeNo ?? entitlement.employeeId}</span></td>
                      <td className="px-3 py-3"><span className="font-semibold">{entitlement.benefitCode}</span><span className="block text-xs text-slate-500">{entitlement.benefitName}</span></td>
                      <td className="px-3 py-3"><span className="font-semibold">{formatMoney(entitlement.amountPerOccurrence)}</span><span className="block text-xs text-slate-500">{scheduleLabel}</span></td>
                      <td className="px-3 py-3 text-xs text-slate-600">{entitlement.effectiveFrom} → {entitlement.effectiveTo ?? 'No end date'}</td>
                      <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${entitlement.isActive ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{entitlement.isActive ? 'ACTIVE' : 'INACTIVE'}</span></td>
                      <td className="px-3 py-3"><div className="flex gap-1.5">
                        <button type="button" aria-label={`Edit ${entitlement.benefitName} entitlement`} onClick={() => startEntitlementEdit(entitlement)} className="rounded border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50"><Pencil className="h-4 w-4" aria-hidden="true" /></button>
                        <button type="button" onClick={() => void toggleEntitlement(entitlement)} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">{entitlement.isActive ? 'Deactivate' : 'Activate'}</button>
                      </div></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {(mode === 'all' || mode === 'deductions' || mode === 'payroll-deductions') && <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Recurring employee deductions</h2>
            <p className="mt-1 text-sm text-slate-500">
              Assign an amount per occurrence, payroll schedule, and effective period to an employee. The assignment is applied only to cutoffs covered by its effective dates and selected schedule.
            </p>
          </div>
          <button
            type="button"
            onClick={resetDeduction}
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 px-3 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50"
          >
            <Plus className="h-4 w-4" aria-hidden="true" /> New deduction
          </button>
        </div>
        <form onSubmit={(event) => void saveDeduction(event)} className="grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-xs font-semibold text-slate-600">
            Employee
            <select required value={deductionDraft.employeeId} onChange={(event) => setDeductionDraft({ ...deductionDraft, employeeId: event.target.value })} className={inputClass}>
              <option value="">Select employee</option>
              {employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.employeeNo} — {employee.fullName}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Deduction type
            <select required disabled={deductionTypesForForm.length === 0} value={deductionDraft.benefitTypeId} onChange={(event) => setDeductionDraft({ ...deductionDraft, benefitTypeId: event.target.value })} className={inputClass}>
              <option value="">
                {deductionTypesForForm.length > 0
                  ? 'Select deduction type'
                  : 'No active deduction types configured'}
              </option>
              {deductionTypesForForm.map((benefit) => <option key={benefit.id} value={benefit.id}>{benefit.code} — {benefit.name}</option>)}
            </select>
            {deductionTypesForForm.length === 0 && (
              <span className="mt-1 block font-normal text-slate-500">
                Add an active Employee Deduction type under Settings → Company Setup → Deduction Types.
              </span>
            )}
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Amount per occurrence (PHP)
            <input required type="number" min="0.01" step="0.01" value={deductionDraft.amountPerOccurrence} onChange={(event) => setDeductionDraft({ ...deductionDraft, amountPerOccurrence: event.target.value })} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Payroll schedule
            <select required value={deductionDraft.schedule} onChange={(event) => setDeductionDraft({ ...deductionDraft, schedule: event.target.value as EmployeeBenefitDeductionInput['schedule'] })} className={inputClass}>
              {deductionSchedules.map((schedule) => <option key={schedule.value} value={schedule.value}>{schedule.label}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Effective from
            <input required type="date" value={deductionDraft.effectiveFrom} onChange={(event) => setDeductionDraft({ ...deductionDraft, effectiveFrom: event.target.value })} className={inputClass} />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Effective to (optional)
            <input type="date" value={deductionDraft.effectiveTo} onChange={(event) => setDeductionDraft({ ...deductionDraft, effectiveTo: event.target.value })} className={inputClass} />
          </label>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-3">
            <button disabled={saving || deductionTypesForForm.length === 0} type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
              <Save className="h-4 w-4" aria-hidden="true" /> {saving ? 'Saving…' : editingDeductionId ? 'Update deduction' : 'Save deduction'}
            </button>
            {editingDeductionId && <button type="button" onClick={resetDeduction} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"><X className="h-4 w-4" aria-hidden="true" /> Cancel</button>}
          </div>
        </form>
        {!deductionDraft.employeeId ? (
          <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">Select an employee above to view their recurring deductions.</p>
        ) : visibleEmployeeDeductions.length === 0 ? (
          <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No recurring deductions found for {selectedDeductionEmployee?.fullName ?? 'the selected employee'}.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Employee</th><th className="px-3 py-2">Deduction</th><th className="px-3 py-2">Amount / schedule</th><th className="px-3 py-2">Effective period</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleEmployeeDeductions.map((deduction) => {
                  const employee = employees.find((person) => person.id === deduction.employeeId)
                  return (
                    <tr key={deduction.id}>
                      <td className="px-3 py-3"><span className="font-medium text-slate-900">{employee?.fullName ?? 'Employee record'}</span><span className="block text-xs text-slate-500">{employee?.employeeNo ?? deduction.employeeId}</span></td>
                      <td className="px-3 py-3"><span className="font-semibold">{deduction.benefitCode}</span><span className="block text-xs text-slate-500">{deduction.benefitName}</span></td>
                      <td className="px-3 py-3"><span className="font-semibold">{formatMoney(deduction.amountPerOccurrence)}</span><span className="block text-xs text-slate-500">{deductionSchedules.find((item) => item.value === deduction.schedule)?.label}</span></td>
                      <td className="px-3 py-3 text-xs text-slate-600">{deduction.effectiveFrom} → {deduction.effectiveTo ?? 'No end date'}</td>
                      <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${deduction.isActive ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{deduction.isActive ? 'ACTIVE' : 'INACTIVE'}</span></td>
                      <td className="px-3 py-3"><div className="flex gap-1.5">
                        <button type="button" aria-label={`Edit ${deduction.benefitName} deduction`} onClick={() => startDeductionEdit(deduction)} className="rounded border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50"><Pencil className="h-4 w-4" aria-hidden="true" /></button>
                        <button type="button" onClick={() => void toggleDeduction(deduction)} className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">{deduction.isActive ? 'Deactivate' : 'Activate'}</button>
                      </div></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {(mode === 'all' || mode === 'entries') && <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Per-cutoff employee benefits</h2>
          <p className="mt-1 text-sm text-slate-500">Enter amounts for the selected cutoff. Entries are immutable after the cutoff is locked.</p>
        </div>
        <label className="block max-w-xl text-xs font-semibold text-slate-600">
          Payroll cutoff
          <select value={selectedCutoffId} onChange={(event) => { setSelectedCutoffId(event.target.value); resetEntry() }} className={inputClass}>
            <option value="">Select cutoff</option>
            {cutoffs.map((cutoff) => <option key={cutoff.id} value={cutoff.id}>{cutoff.code} · {cutoff.periodStart} to {cutoff.periodEnd}{cutoff.locked ? ' · LOCKED' : ''}</option>)}
          </select>
        </label>
        {selectedCutoff?.locked && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This cutoff is locked, so benefit entries are read-only.</p>}

        {canEditEntries && (
          <form onSubmit={(event) => void saveEntry(event)} className="grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs font-semibold text-slate-600">
              Employee
              <select required value={entryDraft.employeeId} onChange={(event) => setEntryDraft({ ...entryDraft, employeeId: event.target.value })} className={inputClass}>
                <option value="">Select employee</option>
                {employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.employeeNo} — {employee.fullName}</option>)}
              </select>
            </label>
            <label className="text-xs font-semibold text-slate-600">
              Benefit
              <select required value={entryDraft.benefitTypeId} onChange={(event) => setEntryDraft({ ...entryDraft, benefitTypeId: event.target.value })} className={inputClass}>
                <option value="">Select benefit</option>
                {entryTypes.map((benefit) => <option key={benefit.id} value={benefit.id}>{benefit.code} — {benefit.name}</option>)}
              </select>
            </label>
            <label className="text-xs font-semibold text-slate-600">
              Amount (PHP)
              <input required type="number" min="0.01" step="0.01" value={entryDraft.amount} onChange={(event) => setEntryDraft({ ...entryDraft, amount: event.target.value })} className={inputClass} />
              {selectedEntryType?.attendanceBased && (
                <span className="mt-1 block font-normal text-slate-500">Full-cutoff amount before paid-day proration and late/undertime deductions.</span>
              )}
            </label>
            <label className="text-xs font-semibold text-slate-600">
              Notes (optional)
              <input maxLength={500} value={entryDraft.notes} onChange={(event) => setEntryDraft({ ...entryDraft, notes: event.target.value })} className={inputClass} />
            </label>
            <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
              <button disabled={saving || entryTypes.length === 0} type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
                <Save className="h-4 w-4" aria-hidden="true" /> {saving ? 'Saving…' : editingEntryId ? 'Update entry' : 'Record benefit'}
              </button>
              {editingEntryId && <button type="button" onClick={() => resetEntry()} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"><X className="h-4 w-4" aria-hidden="true" /> Cancel</button>}
            </div>
          </form>
        )}

        {selectedCutoffId && !entryDraft.employeeId && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">Select an employee above to view their benefits for this cutoff.</p>}
        {entryDraft.employeeId && visibleCutoffEntries.length === 0 && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No benefit entries found for {selectedEntryEmployee?.fullName ?? 'the selected employee'} in this cutoff.</p>}
        {entryDraft.employeeId && visibleCutoffEntries.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Employee</th><th className="px-3 py-2">Benefit</th><th className="px-3 py-2">Tax treatment</th><th className="px-3 py-2">Amount</th><th className="px-3 py-2">Notes</th>{canEditEntries && <th className="px-3 py-2">Actions</th>}</tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visibleCutoffEntries.map((entry) => {
                  const employee = employees.find((person) => person.id === entry.employeeId)
                  return (
                    <tr key={entry.id}>
                      <td className="px-3 py-3"><span className="font-medium text-slate-900">{employee?.fullName ?? 'Employee record'}</span><span className="block text-xs text-slate-500">{employee?.employeeNo ?? entry.employeeId}</span></td>
                      <td className="px-3 py-3"><span className="font-semibold">{entry.benefitCode}</span><span className="block text-xs text-slate-500">{entry.benefitName}</span></td>
                      <td className="px-3 py-3 text-xs">{treatments.find((item) => item.value === entry.taxTreatment)?.label}</td>
                      <td className="whitespace-nowrap px-3 py-3 font-semibold">
                        {formatMoney(entry.amount)}
                        {entry.attendanceBased && <span className="block text-xs font-normal text-slate-500">Full-cutoff basis</span>}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500">{entry.notes ?? '—'}</td>
                      {canEditEntries && <td className="px-3 py-3"><div className="flex gap-1.5">
                        <button type="button" aria-label={`Edit ${entry.benefitName}`} onClick={() => startEntryEdit(entry)} className="rounded border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50"><Pencil className="h-4 w-4" aria-hidden="true" /></button>
                        <button type="button" aria-label={`Delete ${entry.benefitName}`} onClick={() => void deleteEntry(entry)} className="rounded border border-rose-200 p-1.5 text-rose-600 hover:bg-rose-50"><Trash2 className="h-4 w-4" aria-hidden="true" /></button>
                      </div></td>}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {(mode === 'all' || mode === 'entries') && <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Tax-year opening balances</h2>
          <p className="mt-1 text-sm text-slate-500">
            Enter authorized year-to-date amounts from before payroll calculations began in this system. These balances are required for cumulative tax calculation; enter 0 where an employee has no prior amount.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-[minmax(15rem,1fr)_auto] sm:items-end">
          <label className="text-xs font-semibold text-slate-600">
            Employee · tax year {taxYear}
            <select value={ytdEmployeeId} onChange={(event) => setYtdEmployeeId(event.target.value)} className={inputClass}>
              <option value="">Select employee</option>
              {employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.employeeNo} — {employee.fullName}</option>)}
            </select>
          </label>
          {loadingYtd && <p role="status" className="text-xs text-slate-500">Loading saved balances…</p>}
          {ytdEmployeeId && !loadingYtd && (
            <p className={`text-xs font-semibold ${ytdFound ? 'text-emerald-700' : 'text-amber-800'}`}>
              {ytdFound ? 'Opening balance recorded' : 'No opening balance recorded'}
            </p>
          )}
        </div>
        {ytdEmployeeId && (
          <form onSubmit={(event) => void saveYtdBalance(event)} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs font-semibold text-slate-600">
              Prior taxable income (PHP)
              <input required type="number" min="0" step="0.01" value={ytdDraft.taxableIncome} onChange={(event) => setYtdDraft({ ...ytdDraft, taxableIncome: event.target.value })} className={inputClass} />
            </label>
            <label className="text-xs font-semibold text-slate-600">
              Prior tax withheld (PHP)
              <input required type="number" min="0" step="0.01" value={ytdDraft.taxWithheld} onChange={(event) => setYtdDraft({ ...ytdDraft, taxWithheld: event.target.value })} className={inputClass} />
            </label>
            <label className="text-xs font-semibold text-slate-600">
              Prior limited-exempt benefits used (PHP)
              <input required type="number" min="0" step="0.01" value={ytdDraft.exemptLimitedBenefits} onChange={(event) => setYtdDraft({ ...ytdDraft, exemptLimitedBenefits: event.target.value })} className={inputClass} />
            </label>
            <button disabled={saving || loadingYtd} type="submit" className="self-end rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
              {saving ? 'Saving…' : 'Save opening balance'}
            </button>
          </form>
        )}
      </section>}
    </div>
  )
}
