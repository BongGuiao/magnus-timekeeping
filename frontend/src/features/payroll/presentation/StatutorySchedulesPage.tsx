import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Plus, RefreshCw, Save, Trash2, Pencil, Check, Archive, X } from 'lucide-react'
import TopNav, { type NavView } from '../../../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../../../hooks/useCompanySetupSelection'
import { hasPermission } from '../../../types/role'
import type { PayrollUseCases } from '../application/useCases'
import type {
  ContributionBracket,
  ContributionBracketInput,
  ContributionSchedule,
  StatutoryProgram,
  StatutoryScheduleStatus,
  WithholdingTaxBracket,
  WithholdingTaxBracketInput,
  WithholdingTaxSchedule,
} from '../domain/payroll'

type ProgramTab = StatutoryProgram | 'TAX'
type Schedule = ContributionSchedule | WithholdingTaxSchedule
type Bracket = ContributionBracket | WithholdingTaxBracket
type NumericDraft = Record<string, string>

interface Props {
  employeeName: string
  useCases: PayrollUseCases
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const tabs: { id: ProgramTab; label: string; description: string }[] = [
  { id: 'SSS', label: 'SSS', description: 'Social Security System' },
  { id: 'PHILHEALTH', label: 'PhilHealth', description: 'National Health Insurance' },
  { id: 'PAGIBIG', label: 'Pag-IBIG', description: 'Home Development Mutual Fund' },
  { id: 'TAX', label: 'Withholding tax', description: 'Tax brackets by pay period' },
]

const emptySchedule = {
  scheduleName: '',
  effectiveFrom: '',
  effectiveTo: '',
  sourceReference: '',
  taxExemptBenefitLimit: '90000',
  calculationBasis: 'SEMI_MONTHLY' as 'SEMI_MONTHLY' | 'ANNUAL_YTD',
}

const emptyBracket: NumericDraft = {
  bracketNumber: '1',
  min: '0',
  max: '',
  base: '0',
  employeeRate: '0',
  employerRate: '0',
  employeeFixed: '0',
  employerFixed: '0',
  employerAdditional: '0',
  employeeCap: '200',
  employerCap: '200',
  marginalRate: '0',
  excessOver: '0',
}

function nullableNumber(value: string): number | null {
  return value.trim() === '' ? null : Number(value)
}

function amount(value: number): string {
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function dateRange(schedule: Schedule): string {
  return `${schedule.effectiveFrom} — ${schedule.effectiveTo ?? 'No end date'}`
}

function bracketRange(bracket: Bracket): string {
  const minimum = 'annualIncomeMin' in bracket
    ? bracket.annualIncomeMin
    : bracket.compensationMin
  const maximum = 'annualIncomeMax' in bracket
    ? bracket.annualIncomeMax
    : bracket.compensationMax
  return `${amount(minimum)} — ${maximum === null ? 'No maximum' : amount(maximum)}`
}

function statusClasses(status: StatutoryScheduleStatus): string {
  if (status === 'ACTIVE') return 'bg-emerald-100 text-emerald-800'
  if (status === 'RETIRED') return 'bg-slate-100 text-slate-600'
  return 'bg-amber-100 text-amber-800'
}

export default function StatutorySchedulesPage({
  employeeName,
  useCases,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { companyId } = useCompanySetupSelection()
  const [tab, setTab] = useState<ProgramTab>('SSS')
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [brackets, setBrackets] = useState<Bracket[]>([])
  const [scheduleDraft, setScheduleDraft] = useState(emptySchedule)
  const [bracketDraft, setBracketDraft] = useState(emptyBracket)
  const [editingScheduleId, setEditingScheduleId] = useState('')
  const [editingBracketId, setEditingBracketId] = useState('')
  const [isBracketModalOpen, setIsBracketModalOpen] = useState(false)
  const [pendingBracketScrollId, setPendingBracketScrollId] = useState('')
  const [savedBracketId, setSavedBracketId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [thirteenthMonthEnabled, setThirteenthMonthEnabled] = useState(false)
  const [yearEndWtaxReconciliationEnabled, setYearEndWtaxReconciliationEnabled] = useState(false)
  const [scheduleAssignmentApprovalRequired, setScheduleAssignmentApprovalRequired] = useState(true)
  const [statutoryContributionTiming, setStatutoryContributionTiming] =
    useState<'PER_CUTOFF' | 'FINAL_CUTOFF'>('PER_CUTOFF')
  const [statutoryContributionTimingDraft, setStatutoryContributionTimingDraft] =
    useState<'PER_CUTOFF' | 'FINAL_CUTOFF'>('PER_CUTOFF')
  const [savingContributionTiming, setSavingContributionTiming] = useState(false)
  const [contributionTimingSaved, setContributionTimingSaved] = useState(false)
  const [loadedParametersCompanyId, setLoadedParametersCompanyId] = useState('')
  const [parameterLoadErrorCompanyId, setParameterLoadErrorCompanyId] = useState('')
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const bracketModalRef = useRef<HTMLDivElement>(null)
  const savingRef = useRef(saving)
  const bracketModalTitleId = useId()

  const isTax = tab === 'TAX'
  const canManageCompanyParameters = hasPermission('payroll.company_parameters.manage')
  const yearEndSettingsLoading = Boolean(companyId)
    && loadedParametersCompanyId !== companyId
    && parameterLoadErrorCompanyId !== companyId
  const isPagibig = tab === 'PAGIBIG'
  const selected = schedules.find((schedule) => schedule.id === selectedId)
  const taxCalculationBasis = selected && 'calculationBasis' in selected
    ? selected.calculationBasis
    : 'SEMI_MONTHLY'
  const isDraft = selected?.status === 'DRAFT'
  const editingBracket = brackets.find((bracket) => bracket.id === editingBracketId)

  useEffect(() => {
    savingRef.current = saving
  }, [saving])

  useEffect(() => {
    let current = true
    if (!companyId) return () => { current = false }
    useCases.getPayrollSystemParameters(companyId)
      .then((parameters) => {
        if (!current) return
        setThirteenthMonthEnabled(parameters.thirteenthMonthEnabled)
        setYearEndWtaxReconciliationEnabled(parameters.yearEndWtaxReconciliationEnabled)
        setScheduleAssignmentApprovalRequired(parameters.scheduleAssignmentApprovalRequired)
        setStatutoryContributionTiming(parameters.statutoryContributionTiming)
        setStatutoryContributionTimingDraft(parameters.statutoryContributionTiming)
        setLoadedParametersCompanyId(companyId)
        setParameterLoadErrorCompanyId('')
        setContributionTimingSaved(false)
      })
      .catch((cause: unknown) => {
        if (current) {
          setParameterLoadErrorCompanyId(companyId)
          setError(cause instanceof Error
            ? cause.message
            : 'Could not load payroll system parameters.')
        }
      })
    return () => { current = false }
  }, [companyId, useCases])

  async function saveContributionTiming() {
    if (!companyId || loadedParametersCompanyId !== companyId) return
    setSavingContributionTiming(true)
    setContributionTimingSaved(false)
    setError('')
    try {
      const result = await useCases.updatePayrollSystemParameters(companyId, {
        yearEndWtaxReconciliationEnabled,
        thirteenthMonthEnabled,
        scheduleAssignmentApprovalRequired,
        statutoryContributionTiming: statutoryContributionTimingDraft,
      })
      setYearEndWtaxReconciliationEnabled(result.yearEndWtaxReconciliationEnabled)
      setThirteenthMonthEnabled(result.thirteenthMonthEnabled)
      setScheduleAssignmentApprovalRequired(result.scheduleAssignmentApprovalRequired)
      setStatutoryContributionTiming(result.statutoryContributionTiming)
      setStatutoryContributionTimingDraft(result.statutoryContributionTiming)
      setContributionTimingSaved(true)
    } catch (cause) {
      setError(cause instanceof Error
        ? cause.message
        : 'Could not update statutory contribution timing.')
    } finally {
      setSavingContributionTiming(false)
    }
  }

  useEffect(() => {
    if (!isBracketModalOpen) return
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusFrame = window.requestAnimationFrame(() => {
      bracketModalRef.current?.querySelector<HTMLInputElement>('input')?.focus()
    })

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        if (!savingRef.current) resetBracketEditor()
        return
      }

      if (event.key !== 'Tab' || !bracketModalRef.current) return
      const focusable = Array.from(bracketModalRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled])',
      ))
      if (focusable.length === 0) {
        event.preventDefault()
        bracketModalRef.current.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      previouslyFocused?.focus()
    }
  }, [isBracketModalOpen])

  useEffect(() => {
    let current = true
    const request = tab === 'TAX'
      ? useCases.listWithholdingTaxSchedules()
      : useCases.listContributionSchedules(tab)
    request
      .then((result) => {
        if (!current) return
        setSchedules(result)
        setSelectedId((existing) => result.some((schedule) => schedule.id === existing)
          ? existing
          : result[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load statutory schedules.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => { current = false }
  }, [tab, refreshKey, useCases])

  useEffect(() => {
    let current = true
    if (!selectedId) return () => { current = false }
    const request = isTax
      ? useCases.listWithholdingTaxBrackets(selectedId)
      : useCases.listContributionBrackets(selectedId)
    request
      .then((result) => {
        if (current) setBrackets(result)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load schedule brackets.')
      })
    return () => { current = false }
  }, [isTax, selectedId, refreshKey, useCases])

  useEffect(() => {
    if (!pendingBracketScrollId || !brackets.some((bracket) => bracket.id === pendingBracketScrollId)) return
    const frame = window.requestAnimationFrame(() => {
      const row = document.querySelector<HTMLElement>(
        `[data-bracket-id="${pendingBracketScrollId}"]`,
      )
      row?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setPendingBracketScrollId('')
    })
    return () => window.cancelAnimationFrame(frame)
  }, [brackets, pendingBracketScrollId])

  function resetScheduleDraft() {
    setScheduleDraft(emptySchedule)
    setEditingScheduleId('')
  }

  function resetBracketEditor() {
    setEditingBracketId('')
    setIsBracketModalOpen(false)
    setPendingBracketScrollId('')
    setSavedBracketId('')
    setBracketDraft(emptyBracket)
  }

  function refreshData(showLoading = true) {
    if (showLoading) setLoading(true)
    setError('')
    setRefreshKey((key) => key + 1)
  }

  function startScheduleEdit(schedule: Schedule) {
    setEditingScheduleId(schedule.id)
    setScheduleDraft({
      scheduleName: schedule.scheduleName,
      effectiveFrom: schedule.effectiveFrom,
      effectiveTo: schedule.effectiveTo ?? '',
      sourceReference: schedule.sourceReference,
      taxExemptBenefitLimit: 'taxExemptBenefitLimit' in schedule
        ? String(schedule.taxExemptBenefitLimit)
        : '0',
      calculationBasis: 'calculationBasis' in schedule
        ? schedule.calculationBasis
        : 'SEMI_MONTHLY',
    })
  }

  async function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const common = {
        scheduleName: scheduleDraft.scheduleName.trim(),
        effectiveFrom: scheduleDraft.effectiveFrom,
        effectiveTo: scheduleDraft.effectiveTo || null,
        sourceReference: scheduleDraft.sourceReference.trim(),
      }
      const result = isTax
        ? await (editingScheduleId
          ? useCases.updateWithholdingTaxSchedule(editingScheduleId, {
            ...common,
            taxExemptBenefitLimit: Number(scheduleDraft.taxExemptBenefitLimit),
            calculationBasis: scheduleDraft.calculationBasis,
          })
          : useCases.createWithholdingTaxSchedule({
            ...common,
            taxExemptBenefitLimit: Number(scheduleDraft.taxExemptBenefitLimit),
            calculationBasis: scheduleDraft.calculationBasis,
          }))
        : await (editingScheduleId
          ? useCases.updateContributionSchedule(editingScheduleId, { ...common, programCode: tab as StatutoryProgram })
          : useCases.createContributionSchedule({ ...common, programCode: tab as StatutoryProgram }))
      setBrackets([])
      setSelectedId(result.id)
      resetScheduleDraft()
      refreshData()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the schedule.')
    } finally {
      setSaving(false)
    }
  }

  async function deleteSchedule(schedule: Schedule) {
    if (!window.confirm(`Delete the draft schedule "${schedule.scheduleName}"?`)) return
    setError('')
    try {
      if (isTax) await useCases.deleteWithholdingTaxSchedule(schedule.id)
      else await useCases.deleteContributionSchedule(schedule.id)
      setSelectedId('')
      setBrackets([])
      resetScheduleDraft()
      refreshData()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete the schedule.')
    }
  }

  async function changeScheduleStatus(schedule: Schedule, action: 'activate' | 'retire') {
    setError('')
    try {
      if (isTax) {
        if (action === 'activate') await useCases.activateWithholdingTaxSchedule(schedule.id)
        else await useCases.retireWithholdingTaxSchedule(schedule.id)
      } else if (action === 'activate') {
        await useCases.activateContributionSchedule(schedule.id)
      } else {
        await useCases.retireContributionSchedule(schedule.id)
      }
      refreshData()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not ${action} the schedule.`)
    }
  }

  function startBracketEdit(bracket: Bracket) {
    setEditingBracketId(bracket.id)
    setSavedBracketId('')
    setBracketDraft('annualIncomeMin' in bracket
      ? {
        ...emptyBracket,
        bracketNumber: String(bracket.bracketNumber),
        min: String(bracket.annualIncomeMin),
        max: bracket.annualIncomeMax === null
          ? ''
          : String(bracket.annualIncomeMax),
        base: String(bracket.baseTax),
        marginalRate: String(bracket.marginalRate),
        excessOver: String(bracket.excessOver),
      }
      : {
        ...emptyBracket,
        bracketNumber: String(bracket.bracketNumber),
        min: String(bracket.compensationMin),
        max: bracket.compensationMax === null
          ? ''
          : String(bracket.compensationMax),
        base: String(bracket.contributionBase),
        employeeRate: String(bracket.employeeRate),
        employerRate: String(bracket.employerRate),
        employeeFixed: String(bracket.employeeFixedAmount),
        employerFixed: String(bracket.employerFixedAmount),
        employerAdditional: String(bracket.employerAdditionalFixedAmount),
        employeeCap: bracket.employeeContributionCap === null ? '' : String(bracket.employeeContributionCap),
        employerCap: bracket.employerContributionCap === null ? '' : String(bracket.employerContributionCap),
      })
    setIsBracketModalOpen(true)
  }

  function startBracketCreate() {
    setEditingBracketId('')
    setSavedBracketId('')
    const nextBracketNumber = brackets.reduce(
      (highest, bracket) => Math.max(highest, bracket.bracketNumber),
      0,
    ) + 1
    setBracketDraft({
      ...emptyBracket,
      bracketNumber: String(nextBracketNumber),
      ...(isPagibig ? { employeeCap: '200', employerCap: '200' } : {}),
    })
    setIsBracketModalOpen(true)
  }

  async function saveBracket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedId) return
    setSaving(true)
    setError('')
    try {
      const bracketNumber = Number(bracketDraft.bracketNumber)
      const min = Number(bracketDraft.min)
      const max = nullableNumber(bracketDraft.max)
      const result = isTax
        ? await (() => {
          const input: WithholdingTaxBracketInput = {
            bracketNumber,
            annualIncomeMin: min,
            annualIncomeMax: max,
            baseTax: Number(bracketDraft.base),
            marginalRate: Number(bracketDraft.marginalRate),
            excessOver: Number(bracketDraft.excessOver),
          }
          return editingBracketId
            ? useCases.updateWithholdingTaxBracket(editingBracketId, input)
            : useCases.createWithholdingTaxBracket(selectedId, input)
        })()
        : await (() => {
          const input: ContributionBracketInput = {
            bracketNumber,
            compensationMin: min,
            compensationMax: max,
            contributionBase: isPagibig ? 0 : Number(bracketDraft.base),
            employeeRate: Number(bracketDraft.employeeRate),
            employerRate: Number(bracketDraft.employerRate),
            employeeFixedAmount: isPagibig ? 0 : Number(bracketDraft.employeeFixed),
            employerFixedAmount: isPagibig ? 0 : Number(bracketDraft.employerFixed),
            employerAdditionalFixedAmount: isPagibig ? 0 : Number(bracketDraft.employerAdditional),
            employeeContributionCap: isPagibig ? Number(bracketDraft.employeeCap) : null,
            employerContributionCap: isPagibig ? Number(bracketDraft.employerCap) : null,
          }
          return editingBracketId
            ? useCases.updateContributionBracket(editingBracketId, input)
            : useCases.createContributionBracket(selectedId, input)
        })()
      setPendingBracketScrollId(result.id)
      setSavedBracketId(result.id)
      setEditingBracketId('')
      setBracketDraft(emptyBracket)
      setIsBracketModalOpen(false)
      refreshData(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the bracket.')
    } finally {
      setSaving(false)
    }
  }

  async function deleteBracket(bracket: Bracket) {
    if (!window.confirm(`Delete bracket ${bracket.bracketNumber}?`)) return
    setError('')
    try {
      if (isTax) await useCases.deleteWithholdingTaxBracket(bracket.id)
      else await useCases.deleteContributionBracket(bracket.id)
      if (editingBracketId === bracket.id) resetBracketEditor()
      if (savedBracketId === bracket.id) setSavedBracketId('')
      refreshData(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not delete the bracket.')
    }
  }

  function numericField(
    key: keyof NumericDraft,
    label: string,
    options: { optional?: boolean; step?: string } = {},
  ) {
    return (
      <label key={key} className="text-xs font-semibold text-slate-600">
        {label}
        <input
          type="number"
          min="0"
          step={options.step ?? '0.01'}
          required={!options.optional}
          value={bracketDraft[key]}
          onChange={(event) => setBracketDraft((draft) => ({ ...draft, [key]: event.target.value }))}
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
        />
      </label>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="payroll-statutory" onNavigate={onNavigate} onSignOut={onLoggedOut} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-5 py-6">
        <header>
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Payroll setup</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Statutory Setup</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Manage effective-dated contribution and withholding-tax tables. Schedules start as drafts; activation requires a complete bracket range.
            No official rate data is preloaded. Active schedules are used by payroll calculations, so verify each schedule against its official source before activation.
          </p>
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {isTax && !companyId && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Select a company from the company selector above to use its 13th-month payroll settings.
          </p>
        )}

        <nav aria-label="Statutory schedule type" className="grid grid-cols-2 gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm lg:grid-cols-4">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                setTab(item.id)
                setSchedules([])
                setSelectedId('')
                setBrackets([])
                setLoading(true)
                setError('')
                resetScheduleDraft()
                resetBracketEditor()
              }}
              aria-current={tab === item.id ? 'page' : undefined}
              className={`rounded-lg px-4 py-3 text-left transition ${tab === item.id ? 'bg-indigo-600 text-white' : 'text-slate-700 hover:bg-indigo-50 hover:text-indigo-700'}`}
            >
              <span className="block text-sm font-bold">{item.label}</span>
              <span className={`mt-0.5 block text-xs ${tab === item.id ? 'text-indigo-100' : 'text-slate-500'}`}>{item.description}</span>
            </button>
          ))}
        </nav>

        {!isTax && companyId && (
          <section className="flex flex-wrap items-end justify-between gap-4 rounded-xl border border-indigo-100 bg-indigo-50 p-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Statutory contribution deduction timing</h2>
              <p className="mt-1 text-sm text-slate-600">
                Applies to SSS, PhilHealth, and Pag-IBIG for this company.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="min-w-64 text-xs font-semibold text-slate-600">
                Deduction timing
                <select
                  aria-label="Statutory contribution deduction timing"
                  value={statutoryContributionTimingDraft}
                  disabled={!canManageCompanyParameters || yearEndSettingsLoading || savingContributionTiming}
                  onChange={(event) => {
                    setStatutoryContributionTimingDraft(
                      event.target.value === 'FINAL_CUTOFF' ? 'FINAL_CUTOFF' : 'PER_CUTOFF',
                    )
                    setContributionTimingSaved(false)
                  }}
                  className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900"
                >
                  <option value="PER_CUTOFF">Every payroll cutoff</option>
                  <option value="FINAL_CUTOFF">Final cutoff of each month only</option>
                </select>
              </label>
              {canManageCompanyParameters && (
                <button
                  type="button"
                  onClick={() => void saveContributionTiming()}
                  disabled={yearEndSettingsLoading || savingContributionTiming
                    || statutoryContributionTimingDraft === statutoryContributionTiming}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingContributionTiming ? 'Saving…' : 'Save timing'}
                </button>
              )}
              {canManageCompanyParameters && contributionTimingSaved && (
                <p role="status" className="text-sm font-medium text-emerald-700">
                  Deduction timing saved for this company.
                </p>
              )}
            </div>
            {!canManageCompanyParameters && (
              <p className="w-full text-xs text-slate-500">
                You can view this setting, but need Company Parameters permission to change it.
              </p>
            )}
          </section>
        )}

        <div className="grid gap-5 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.6fr)]">
          <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-slate-900">{isTax ? 'Withholding tax schedules' : `${tab} schedules`}</h2>
              <button
                type="button"
                onClick={() => { setSelectedId(''); setBrackets([]); resetScheduleDraft(); resetBracketEditor() }}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                <Plus className="h-4 w-4" aria-hidden="true" /> New
              </button>
            </div>
            {loading && <p role="status" className="text-sm text-slate-500">Loading schedules…</p>}
            {!loading && schedules.length === 0 && (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">No schedules yet. Create a draft schedule to enter a source and effective date.</p>
            )}
            <ul className="space-y-2">
              {schedules.map((schedule) => (
                <li key={schedule.id}>
                  <button
                    type="button"
                    onClick={() => { setSelectedId(schedule.id); setBrackets([]); resetScheduleDraft(); resetBracketEditor() }}
                    aria-pressed={selectedId === schedule.id}
                    className={`w-full rounded-lg border p-3 text-left ${selectedId === schedule.id ? 'border-indigo-300 bg-indigo-50' : 'border-slate-200 hover:border-indigo-200'}`}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="font-semibold text-slate-900">{schedule.scheduleName}</span>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${statusClasses(schedule.status)}`}>{schedule.status}</span>
                    </span>
                    <span className="mt-1 block text-xs text-slate-500">{dateRange(schedule)}</span>
                    <span className="mt-1 block truncate text-xs text-slate-500">{schedule.sourceReference}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <div className="space-y-5">
            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-bold text-slate-900">{editingScheduleId ? 'Edit draft schedule' : selected ? selected.scheduleName : 'Create schedule'}</h2>
                  {selected && <p className="mt-1 text-xs text-slate-500">Status: {selected.status} · Version {selected.rowVersion}</p>}
                </div>
                {selected && (
                  <div className="flex flex-wrap gap-2">
                    {selected.status === 'DRAFT' && (
                      <>
                        <button type="button" aria-label="Edit schedule" title="Edit schedule" onClick={() => startScheduleEdit(selected)} className="rounded-lg border border-slate-300 p-2 text-slate-600 hover:bg-slate-50">
                          <Pencil className="h-4 w-4" aria-hidden="true" />
                        </button>
                        <button type="button" aria-label="Delete schedule" title="Delete schedule" onClick={() => void deleteSchedule(selected)} className="rounded-lg border border-rose-200 p-2 text-rose-600 hover:bg-rose-50">
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </button>
                        <button type="button" onClick={() => void changeScheduleStatus(selected, 'activate')} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-700">
                          <Check className="h-4 w-4" aria-hidden="true" /> Activate
                        </button>
                      </>
                    )}
                    {selected.status === 'ACTIVE' && (
                      <button type="button" onClick={() => void changeScheduleStatus(selected, 'retire')} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                        <Archive className="h-4 w-4" aria-hidden="true" /> Retire
                      </button>
                    )}
                  </div>
                )}
              </div>
              {(!selected || editingScheduleId) && (
                <form onSubmit={(event) => void saveSchedule(event)} className="grid gap-3 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-slate-600 sm:col-span-2">
                    Schedule name
                    <input required maxLength={120} value={scheduleDraft.scheduleName} onChange={(event) => setScheduleDraft({ ...scheduleDraft, scheduleName: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
                  </label>
                  <label className="text-xs font-semibold text-slate-600">
                    Effective from
                    <input required type="date" value={scheduleDraft.effectiveFrom} onChange={(event) => setScheduleDraft({ ...scheduleDraft, effectiveFrom: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
                  </label>
                  <label className="text-xs font-semibold text-slate-600">
                    Effective to (optional)
                    <input type="date" value={scheduleDraft.effectiveTo} onChange={(event) => setScheduleDraft({ ...scheduleDraft, effectiveTo: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
                  </label>
                  {isTax && (
                    <>
                      <p className="self-center text-xs text-slate-600">
                        {scheduleDraft.calculationBasis === 'SEMI_MONTHLY'
                          ? 'Brackets apply directly to semi-monthly taxable pay. This schedule requires two payroll periods per month.'
                          : 'This existing schedule uses annual YTD tax calculations; its basis is retained while editing.'}
                      </p>
                      <label className="text-xs font-semibold text-slate-600">
                        Tax-exempt benefit limit
                        <input required type="number" min="0" step="0.01" value={scheduleDraft.taxExemptBenefitLimit} onChange={(event) => setScheduleDraft({ ...scheduleDraft, taxExemptBenefitLimit: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
                      </label>
                    </>
                  )}
                  <label className={`text-xs font-semibold text-slate-600 ${isTax ? '' : 'sm:col-span-2'}`}>
                    Source reference
                    <input required value={scheduleDraft.sourceReference} onChange={(event) => setScheduleDraft({ ...scheduleDraft, sourceReference: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" placeholder="Circular, law, or official source URL" />
                  </label>
                  <div className="flex gap-2 sm:col-span-2">
                    <button disabled={saving} type="submit" className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
                      <Save className="h-4 w-4" aria-hidden="true" /> {saving ? 'Saving…' : 'Save draft'}
                    </button>
                    {editingScheduleId && <button type="button" onClick={resetScheduleDraft} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"><X className="h-4 w-4" aria-hidden="true" /> Cancel</button>}
                  </div>
                </form>
              )}
              {selected && !editingScheduleId && (
                <dl className="grid gap-3 text-sm sm:grid-cols-2">
                  <div><dt className="text-xs font-semibold text-slate-500">Effective period</dt><dd className="mt-1 text-slate-900">{dateRange(selected)}</dd></div>
                  {'taxExemptBenefitLimit' in selected && <>
                    <div><dt className="text-xs font-semibold text-slate-500">Tax calculation basis</dt><dd className="mt-1 text-slate-900">{selected.calculationBasis === 'SEMI_MONTHLY' ? 'Semi-monthly taxable pay' : 'Annual YTD taxable income'}</dd></div>
                    <div><dt className="text-xs font-semibold text-slate-500">Tax-exempt benefit limit</dt><dd className="mt-1 text-slate-900">{amount(selected.taxExemptBenefitLimit)}</dd></div>
                  </>}
                  <div className="sm:col-span-2"><dt className="text-xs font-semibold text-slate-500">Source reference</dt><dd className="mt-1 break-all text-slate-900">{selected.sourceReference}</dd></div>
                </dl>
              )}
            </section>

            {selected && (
              <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-lg font-bold text-slate-900">Brackets</h2>
                    <p className="text-xs text-slate-500">
                      {isPagibig
                        ? 'Pag-IBIG rates apply to monthly basic salary; each share is capped monthly, then allocated across payroll cutoffs.'
                        : 'Bracket amounts and rates are stored as entered; rates use decimal fractions (for example, 0.05 = 5%).'}
                    </p>
                  </div>
                  {isDraft && <button type="button" onClick={startBracketCreate} className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 px-3 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50"><Plus className="h-4 w-4" aria-hidden="true" /> Add bracket</button>}
                </div>

                {brackets.length === 0 && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No brackets have been entered for this schedule.</p>}
                {brackets.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[42rem] border-collapse text-left text-xs">
                      <thead className="bg-slate-50 text-slate-500">
                        <tr>
                          <th className="p-2">#</th>
                          <th className="p-2">{isTax
                            ? taxCalculationBasis === 'SEMI_MONTHLY' ? 'Semi-monthly taxable pay' : 'Annual taxable income'
                            : isPagibig ? 'Monthly basic salary' : 'Compensation range'}</th>
                          {isTax
                            ? <><th className="p-2">Base tax</th><th className="p-2">Marginal rate</th><th className="p-2">Excess over</th></>
                            : <>{!isPagibig && <th className="p-2">Contribution base</th>}<th className="p-2">Employee</th><th className="p-2">Employer</th>{!isPagibig && <th className="p-2">Employer additional</th>}</>}
                          {isDraft && <th className="p-2">Actions</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {brackets.map((bracket) => {
                          const rowIsTax = 'annualIncomeMin' in bracket
                          return (
                            <tr
                              key={bracket.id}
                              data-bracket-id={bracket.id}
                              className={`border-t text-slate-700 transition-colors ${
                                editingBracketId === bracket.id
                                  ? 'bg-amber-50 ring-2 ring-inset ring-amber-400'
                                  : savedBracketId === bracket.id
                                    ? 'bg-emerald-50 ring-2 ring-inset ring-emerald-300'
                                    : 'border-slate-100'
                              }`}
                            >
                              <td className="p-2">{bracket.bracketNumber}</td>
                              <td className="p-2">{rowIsTax
                                ? `${amount(bracket.annualIncomeMin)} — ${bracket.annualIncomeMax === null ? 'No maximum' : amount(bracket.annualIncomeMax)}`
                                : `${amount(bracket.compensationMin)} — ${bracket.compensationMax === null ? 'No maximum' : amount(bracket.compensationMax)}`}</td>
                              {rowIsTax
                                ? <><td className="p-2">{amount(bracket.baseTax)}</td><td className="p-2">{(bracket.marginalRate * 100).toFixed(3)}%</td><td className="p-2">{amount(bracket.excessOver)}</td></>
                                : isPagibig
                                  ? <><td className="p-2">{(bracket.employeeRate * 100).toFixed(3)}%<span className="block text-slate-500">Max {amount(bracket.employeeContributionCap ?? 0)}/month</span></td><td className="p-2">{(bracket.employerRate * 100).toFixed(3)}%<span className="block text-slate-500">Max {amount(bracket.employerContributionCap ?? 0)}/month</span></td></>
                                  : <><td className="p-2">{amount(bracket.contributionBase)}</td><td className="p-2">{amount(bracket.employeeFixedAmount)} + {(bracket.employeeRate * 100).toFixed(3)}%</td><td className="p-2">{amount(bracket.employerFixedAmount)} + {(bracket.employerRate * 100).toFixed(3)}%</td><td className="p-2">{amount(bracket.employerAdditionalFixedAmount)}</td></>}
                              {isDraft && <td className="p-2">
                                <div className="flex gap-1">
                                  <button type="button" aria-label={`Edit bracket ${bracket.bracketNumber}`} onClick={() => startBracketEdit(bracket)} className="rounded border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50"><Pencil className="h-3.5 w-3.5" aria-hidden="true" /></button>
                                  <button type="button" aria-label={`Delete bracket ${bracket.bracketNumber}`} onClick={() => void deleteBracket(bracket)} className="rounded border border-rose-200 p-1.5 text-rose-600 hover:bg-rose-50"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /></button>
                                </div>
                              </td>}
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

              </section>
            )}
          </div>
        </div>
      </main>
      {isBracketModalOpen && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/55 p-0 backdrop-blur-[2px] sm:items-center sm:p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !saving) resetBracketEditor()
          }}
        >
          <div
            ref={bracketModalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={bracketModalTitleId}
            tabIndex={-1}
            className="flex max-h-[94svh] w-full max-w-3xl flex-col overflow-hidden rounded-t-lg border border-slate-200 bg-white shadow-2xl outline-none sm:rounded-lg"
          >
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
              <div>
                <h2 id={bracketModalTitleId} className="text-lg font-bold text-slate-900">
                  {editingBracketId ? `Edit bracket ${bracketDraft.bracketNumber}` : 'Add bracket'}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  Enter bracket values. Rates use decimal fractions (for example, 0.05 = 5%).
                </p>
                {editingBracket && (
                  <p className="mt-1 text-xs font-medium text-amber-800">
                    Current range: {bracketRange(editingBracket)}
                  </p>
                )}
              </div>
              <button
                type="button"
                aria-label="Close bracket editor"
                onClick={resetBracketEditor}
                disabled={saving}
                className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <form onSubmit={(event) => void saveBracket(event)} className="min-h-0 overflow-y-auto">
              <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3 sm:px-6">
                {numericField('bracketNumber', 'Bracket number', { step: '1' })}
                {numericField('min', isTax
                  ? taxCalculationBasis === 'SEMI_MONTHLY' ? 'Semi-monthly taxable pay minimum' : 'Annual taxable income minimum'
                  : isPagibig ? 'Monthly basic salary minimum' : 'Compensation minimum')}
                {numericField('max', isTax
                  ? 'Taxable pay maximum (blank = no maximum)'
                  : 'Maximum (blank = no maximum)', { optional: true })}
                {isTax && numericField('base', 'Base tax')}
                {isTax
                  ? <>{numericField('marginalRate', 'Marginal rate (decimal)', { step: '0.000001' })}{numericField('excessOver', 'Excess over')}</>
                  : <>{numericField('employeeRate', 'Employee rate (decimal)', { step: '0.000001' })}{numericField('employerRate', 'Employer rate (decimal)', { step: '0.000001' })}{isPagibig
                    ? <>{numericField('employeeCap', 'Employee monthly cap')}{numericField('employerCap', 'Employer monthly cap')}</>
                    : <>{numericField('base', 'Contribution base')}{numericField('employeeFixed', 'Employee fixed amount')}{numericField('employerFixed', 'Employer fixed amount')}{numericField('employerAdditional', 'Employer additional fixed amount')}</>}</>}
              </div>
              {error && <p role="alert" className="mx-5 mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 sm:mx-6">{error}</p>}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-6">
                {savedBracketId && (
                  <p role="status" className="text-sm font-medium text-emerald-700">
                    Bracket saved. It is highlighted in the table.
                  </p>
                )}
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={resetBracketEditor}
                    disabled={saving}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    disabled={saving}
                    type="submit"
                    className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
                  >
                    {editingBracketId ? <RefreshCw className="h-4 w-4" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
                    {saving ? 'Saving…' : editingBracketId ? 'Update bracket' : 'Save bracket'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
