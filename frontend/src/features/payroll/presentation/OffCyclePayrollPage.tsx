import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react'
import { BadgeCheck, Download, FileUp, Gift, RefreshCw, Send, Trash2, Wallet, X } from 'lucide-react'
import TopNav, { type NavView } from '../../../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../../../hooks/useCompanySetupSelection'
import type { PayrollUseCases } from '../application/useCases'
import { parseOffCycleCsv, type OffCyclePayrollUseCases } from '../application/offCycleUseCases'
import type { BenefitType, PayrollGroupOption } from '../domain/payroll'
import {
  isOffCycleActionAllowed,
  isOffCycleBenefitType,
  isThirteenthMonthBenefitType,
  type OffCyclePayrollRun,
  type OffCycleRunStatus,
  type OffCycleUploadRow,
  type ThirteenthMonthSource,
} from '../domain/offCycle'

interface Props {
  employeeName: string
  payrollUseCases: PayrollUseCases
  offCycleUseCases: OffCyclePayrollUseCases
  canManage: boolean
  canApprove: boolean
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

type CreateMode = 'BENEFIT' | 'THIRTEENTH_MONTH'

const inputClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'
const labelClass = 'block text-xs font-bold uppercase tracking-wide text-slate-500'
const buttonClass = 'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50'
const statuses: OffCycleRunStatus[] = ['DRAFT', 'PENDING', 'APPROVED', 'PAID', 'REJECTED']
const statusStyles: Record<OffCycleRunStatus, string> = {
  DRAFT: 'bg-slate-100 text-slate-700',
  PENDING: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-sky-100 text-sky-800',
  PAID: 'bg-emerald-100 text-emerald-800',
  REJECTED: 'bg-rose-100 text-rose-700',
}
const statusLabels: Record<OffCycleRunStatus, string> = {
  DRAFT: 'Draft',
  PENDING: 'Pending approval',
  APPROVED: 'Approved',
  PAID: 'Paid',
  REJECTED: 'Rejected',
}
const today = new Date().toISOString().slice(0, 10)
const csvTemplate = 'employee_no,amount,notes\nEMP-0001,5000.00,Q4 performance incentive\n'

function money(value: number): string {
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function dateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

function StatusBadge({ status }: { status: OffCycleRunStatus }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-bold ${statusStyles[status]}`}>
      {statusLabels[status]}
    </span>
  )
}

export default function OffCyclePayrollPage({
  employeeName,
  payrollUseCases,
  offCycleUseCases,
  canManage,
  canApprove,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { companyId } = useCompanySetupSelection()
  const [groups, setGroups] = useState<PayrollGroupOption[]>([])
  const [groupFilter, setGroupFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<OffCycleRunStatus | ''>('')
  const [runs, setRuns] = useState<OffCyclePayrollRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [selectedRun, setSelectedRun] = useState<OffCyclePayrollRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [createGroupId, setCreateGroupId] = useState('')
  const [createMode, setCreateMode] = useState<CreateMode>('BENEFIT')
  const [benefitTypes, setBenefitTypes] = useState<BenefitType[]>([])
  const [benefitTypeId, setBenefitTypeId] = useState('')
  const [sources, setSources] = useState<ThirteenthMonthSource[]>([])
  const [sourceId, setSourceId] = useState('')
  const [proposedDate, setProposedDate] = useState(today)
  const [notes, setNotes] = useState('')
  const [uploadRows, setUploadRows] = useState<OffCycleUploadRow[]>([])
  const [fileName, setFileName] = useState('')
  const [fileInputKey, setFileInputKey] = useState(0)

  const [rejectReason, setRejectReason] = useState('')
  const [actualPaymentDate, setActualPaymentDate] = useState(today)

  const groupLabels = useMemo(
    () => new Map(groups.map((group) => [group.id, `${group.code} — ${group.name}`])),
    [groups],
  )
  const eligibleBenefitTypes = benefitTypes.filter(
    createMode === 'BENEFIT' ? isOffCycleBenefitType : isThirteenthMonthBenefitType,
  )
  const selectedBenefitType = eligibleBenefitTypes.find((item) => item.id === benefitTypeId)
    ?? eligibleBenefitTypes[0]
  const effectiveBenefitTypeId = selectedBenefitType?.id ?? ''
  const effectiveSourceId = sources.some((item) => item.id === sourceId) ? sourceId : sources[0]?.id ?? ''
  const uploadTotal = uploadRows.reduce((sum, row) => sum + row.amount, 0)

  useEffect(() => {
    let current = true
    setGroups([])
    setGroupFilter('')
    setCreateGroupId('')
    if (!companyId || !canManage) return () => { current = false }
    payrollUseCases.listPayrollGroups(companyId)
      .then((nextGroups) => {
        if (!current) return
        setGroups(nextGroups)
        setCreateGroupId(nextGroups[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(errorMessage(cause, 'Could not load payroll groups.'))
      })
    return () => { current = false }
  }, [canManage, companyId, payrollUseCases])

  useEffect(() => {
    let current = true
    setBenefitTypes([])
    setSources([])
    if (!createGroupId || !canManage) return () => { current = false }
    Promise.all([
      payrollUseCases.listBenefitTypes(createGroupId),
      offCycleUseCases.listThirteenthMonthSources(createGroupId),
    ])
      .then(([nextTypes, nextSources]) => {
        if (!current) return
        setBenefitTypes(nextTypes)
        setSources(nextSources)
      })
      .catch((cause: unknown) => {
        if (current) setError(errorMessage(cause, 'Could not load benefit types.'))
      })
    return () => { current = false }
  }, [canManage, createGroupId, offCycleUseCases, payrollUseCases])

  const loadRuns = useCallback(async () => {
    if (!companyId) {
      setRuns([])
      return
    }
    setLoadingRuns(true)
    try {
      setRuns(await offCycleUseCases.listRuns({
        companyId,
        payrollGroupId: groupFilter || undefined,
        status: statusFilter || undefined,
      }))
    } catch (cause) {
      setError(errorMessage(cause, 'Could not load off-cycle payroll runs.'))
    } finally {
      setLoadingRuns(false)
    }
  }, [companyId, groupFilter, offCycleUseCases, statusFilter])

  useEffect(() => {
    setSelectedRun(null)
    void loadRuns()
  }, [loadRuns])

  async function runAction(action: () => Promise<OffCyclePayrollRun | void>, success: string) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await action()
      setSelectedRun(result ?? null)
      setNotice(success)
    } catch (cause) {
      setError(errorMessage(cause, 'The off-cycle action failed.'))
      if (selectedRun) {
        // Approval may save recalculated amounts before failing; reload so the approver sees them.
        setSelectedRun(await offCycleUseCases.getRun(selectedRun.id).catch(() => selectedRun))
      }
    } finally {
      setBusy(false)
      await loadRuns()
    }
  }

  async function openRun(runId: string) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      setSelectedRun(await offCycleUseCases.getRun(runId))
      setRejectReason('')
      setActualPaymentDate(today)
    } catch (cause) {
      setError(errorMessage(cause, 'Could not open the off-cycle run.'))
    } finally {
      setBusy(false)
    }
  }

  async function readUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    setUploadRows([])
    setFileName('')
    setError('')
    if (!file) return
    try {
      setUploadRows(parseOffCycleCsv(await file.text()))
      setFileName(file.name)
    } catch (cause) {
      setError(errorMessage(cause, 'Could not read the CSV file.'))
      setFileInputKey((key) => key + 1)
    }
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([csvTemplate], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'off-cycle-incentives-template.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  async function createRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await runAction(async () => {
      const run = createMode === 'BENEFIT'
        ? await offCycleUseCases.createBenefitRun({
          payrollGroupId: createGroupId,
          benefitTypeId: effectiveBenefitTypeId,
          proposedPaymentDate: proposedDate,
          notes,
          rows: uploadRows,
        })
        : await offCycleUseCases.createThirteenthMonthRun({
          payrollGroupId: createGroupId,
          benefitTypeId: effectiveBenefitTypeId,
          thirteenthMonthRunId: effectiveSourceId,
          proposedPaymentDate: proposedDate,
          notes,
        })
      setUploadRows([])
      setFileName('')
      setFileInputKey((key) => key + 1)
      setNotes('')
      if (createMode === 'THIRTEENTH_MONTH') {
        setSources(await offCycleUseCases.listThirteenthMonthSources(createGroupId))
      }
      return run
    }, 'Draft created. Review the computed withholding tax, then submit it for approval.')
  }

  const run = selectedRun
  const can = (action: Parameters<typeof isOffCycleActionAllowed>[1]) => (
    run !== null && isOffCycleActionAllowed(run.status, action)
  )

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView="payroll-off-cycle" onNavigate={onNavigate} onSignOut={onLoggedOut} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-5 py-6">
        <header className="flex items-start gap-3">
          <span className="mt-1 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-100 text-indigo-700">
            <Gift className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Payroll</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Off-cycle payroll</h1>
            <p className="mt-1 max-w-4xl text-sm text-slate-600">
              Release incentives and 13th-month pay outside the regular cutoff. Tax treatment follows the selected
              benefit type, and paid amounts count toward the employee&apos;s year-to-date tax on the actual release date.
            </p>
          </div>
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
        {!companyId && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Select a company from the company selector above to manage off-cycle payroll runs.
          </p>
        )}

        {companyId && canManage && (
          <form onSubmit={createRun} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-slate-900">Prepare a new run</h2>
              <div role="tablist" aria-label="Run type" className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
                {(['BENEFIT', 'THIRTEENTH_MONTH'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={createMode === mode}
                    onClick={() => setCreateMode(mode)}
                    className={`rounded-md px-3 py-1.5 text-sm font-semibold ${createMode === mode ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:text-indigo-700'}`}
                  >
                    {mode === 'BENEFIT' ? 'Incentive upload (CSV)' : '13th-month pay'}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-4">
              <label className={labelClass}>
                Payroll group
                <select value={createGroupId} onChange={(event) => setCreateGroupId(event.target.value)} className={inputClass} required>
                  {groups.map((group) => <option key={group.id} value={group.id}>{group.code} — {group.name}</option>)}
                </select>
              </label>
              <label className={labelClass}>
                Benefit type
                <select value={effectiveBenefitTypeId} onChange={(event) => setBenefitTypeId(event.target.value)} className={inputClass} required>
                  {!eligibleBenefitTypes.length && <option value="">No eligible benefit types</option>}
                  {eligibleBenefitTypes.map((item) => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
                </select>
              </label>
              <label className={labelClass}>
                Proposed release date
                <input type="date" value={proposedDate} onChange={(event) => setProposedDate(event.target.value)} className={inputClass} required />
              </label>
              <label className={labelClass}>
                Notes
                <input value={notes} maxLength={500} onChange={(event) => setNotes(event.target.value)} className={inputClass} placeholder="Optional" />
              </label>
            </div>

            {selectedBenefitType && (
              <p className="text-xs text-slate-500">
                Tax treatment: <strong>{selectedBenefitType.taxTreatment}</strong> · Withholding:{' '}
                <strong>{selectedBenefitType.withholdingTiming === 'YEAR_END' ? 'deferred to year-end' : 'on release'}</strong>
              </p>
            )}
            {createMode === 'BENEFIT' && !eligibleBenefitTypes.length && createGroupId && (
              <p className="text-xs text-amber-700">Configure an active cash allowance, one-time bonus, or reimbursement benefit type for this group first.</p>
            )}
            {createMode === 'THIRTEENTH_MONTH' && !eligibleBenefitTypes.length && createGroupId && (
              <p className="text-xs text-amber-700">13th-month pay requires an active ONE_TIME_BONUS benefit type with EXEMPT_LIMITED tax treatment.</p>
            )}

            {createMode === 'BENEFIT' ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-end gap-3">
                  <label className={`${labelClass} min-w-72`}>
                    Incentive CSV (employee_no, amount, notes)
                    <input key={fileInputKey} type="file" accept=".csv,text/csv" onChange={readUpload} className={inputClass} />
                  </label>
                  <button type="button" onClick={downloadTemplate} className={`${buttonClass} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}>
                    <Download className="h-4 w-4" aria-hidden="true" /> Template
                  </button>
                </div>
                {uploadRows.length > 0 && (
                  <div className="rounded-lg border border-slate-200">
                    <p className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                      <strong>{fileName}</strong>: {uploadRows.length} employee(s), total {money(uploadTotal)}
                    </p>
                    <div className="max-h-64 overflow-auto">
                      <table className="min-w-full text-sm">
                        <thead className="sticky top-0 bg-white text-left text-xs uppercase text-slate-500">
                          <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Employee no.</th><th className="px-3 py-2 text-right">Amount</th><th className="px-3 py-2">Notes</th></tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {uploadRows.map((row) => (
                            <tr key={row.rowNumber}>
                              <td className="px-3 py-1.5 text-slate-500">{row.rowNumber}</td>
                              <td className="px-3 py-1.5 font-medium">{row.employeeNo}</td>
                              <td className="px-3 py-1.5 text-right tabular-nums">{money(row.amount)}</td>
                              <td className="px-3 py-1.5 text-slate-600">{row.notes}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <label className={`${labelClass} max-w-xl`}>
                13th-month calculation to release
                <select value={effectiveSourceId} onChange={(event) => setSourceId(event.target.value)} className={inputClass} required>
                  {!sources.length && <option value="">No unpaid 13th-month calculations</option>}
                  {sources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.taxYear} · {source.coveredPeriodFrom ?? '?'} to {source.coveredPeriodTo ?? '?'} · {source.resultCount} employee(s)
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={busy || !effectiveBenefitTypeId || (createMode === 'BENEFIT' ? !uploadRows.length : !effectiveSourceId)}
                className={`${buttonClass} bg-indigo-600 text-white hover:bg-indigo-700`}
              >
                <FileUp className="h-4 w-4" aria-hidden="true" /> Create draft
              </button>
            </div>
          </form>
        )}

        {companyId && (
          <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 p-4">
              <h2 className="text-lg font-bold text-slate-900">Off-cycle runs</h2>
              <div className="flex flex-wrap items-end gap-3">
                {groups.length > 0 && (
                  <label className={labelClass}>
                    Payroll group
                    <select value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)} className={inputClass}>
                      <option value="">All groups</option>
                      {groups.map((group) => <option key={group.id} value={group.id}>{group.code} — {group.name}</option>)}
                    </select>
                  </label>
                )}
                <label className={labelClass}>
                  Status
                  <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as OffCycleRunStatus | '')} className={inputClass}>
                    <option value="">All statuses</option>
                    {statuses.map((value) => <option key={value} value={value}>{statusLabels[value]}</option>)}
                  </select>
                </label>
                <button type="button" onClick={() => void loadRuns()} className={`${buttonClass} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}>
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
                </button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Benefit</th>
                    {groups.length > 0 && <th className="px-4 py-2">Payroll group</th>}
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2">Release date</th>
                    <th className="px-4 py-2 text-right">Employees</th>
                    <th className="px-4 py-2 text-right">Gross</th>
                    <th className="px-4 py-2 text-right">Withholding tax</th>
                    <th className="px-4 py-2 text-right">Net</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.map((item) => (
                    <tr key={item.id} className={item.id === run?.id ? 'bg-indigo-50' : undefined}>
                      <td className="px-4 py-2">
                        <span className="font-semibold text-slate-900">{item.benefitCode}</span>{' '}
                        <span className="text-slate-500">{item.runType === 'THIRTEENTH_MONTH' ? '(13th month)' : item.benefitName}</span>
                      </td>
                      {groups.length > 0 && <td className="px-4 py-2 text-slate-600">{groupLabels.get(item.payrollGroupId) ?? '—'}</td>}
                      <td className="px-4 py-2"><StatusBadge status={item.status} /></td>
                      <td className="px-4 py-2">{item.actualPaymentDate ?? `${item.proposedPaymentDate} (proposed)`}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{item.employeeCount}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{money(item.totalAmount)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{money(item.totalWithholdingTax)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{money(item.totalNetAmount)}</td>
                      <td className="px-4 py-2 text-right">
                        <button type="button" onClick={() => void openRun(item.id)} className="font-semibold text-indigo-600 hover:text-indigo-800">
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!runs.length && (
                    <tr><td colSpan={9} className="px-4 py-6 text-center text-slate-500">{loadingRuns ? 'Loading…' : 'No off-cycle runs found.'}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {run && (
          <section className="space-y-4 rounded-xl border border-indigo-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900">
                  {run.benefitCode} — {run.benefitName} <StatusBadge status={run.status} />
                </h2>
                <p className="mt-1 text-sm text-slate-600">
                  Proposed release {run.proposedPaymentDate}
                  {run.actualPaymentDate && <> · Released {run.actualPaymentDate}</>}
                  {' '}· Prepared {dateTime(run.createdAt)}
                  {run.submittedAt && <> · Submitted {dateTime(run.submittedAt)}</>}
                  {run.approvedAt && <> · Approved {dateTime(run.approvedAt)}</>}
                </p>
                {run.notes && <p className="mt-1 text-sm text-slate-600">Notes: {run.notes}</p>}
                {run.rejectionReason && <p className="mt-1 text-sm font-medium text-rose-700">Rejected: {run.rejectionReason}</p>}
              </div>
              <button type="button" aria-label="Close run details" onClick={() => setSelectedRun(null)} className="rounded-lg p-1 text-slate-500 hover:bg-slate-100">
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div className="flex flex-wrap items-end gap-2">
              {canManage && can('RECALCULATE') && (
                <button type="button" disabled={busy} onClick={() => void runAction(() => offCycleUseCases.recalculateRun(run.id), 'Withholding tax recalculated.')} className={`${buttonClass} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}>
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> Recalculate
                </button>
              )}
              {canManage && can('SUBMIT') && (
                <button type="button" disabled={busy} onClick={() => void runAction(() => offCycleUseCases.submitRun(run.id), 'Submitted for HR / Payroll Admin approval.')} className={`${buttonClass} bg-indigo-600 text-white hover:bg-indigo-700`}>
                  <Send className="h-4 w-4" aria-hidden="true" /> Submit for approval
                </button>
              )}
              {canApprove && can('APPROVE') && (
                <button type="button" disabled={busy} onClick={() => void runAction(() => offCycleUseCases.approveRun(run.id), 'Off-cycle run approved for release.')} className={`${buttonClass} bg-emerald-600 text-white hover:bg-emerald-700`}>
                  <BadgeCheck className="h-4 w-4" aria-hidden="true" /> Approve
                </button>
              )}
              {canApprove && can('REJECT') && (
                <div className="flex items-end gap-2">
                  <label className={labelClass}>
                    Rejection reason
                    <input value={rejectReason} maxLength={500} onChange={(event) => setRejectReason(event.target.value)} className={inputClass} />
                  </label>
                  <button type="button" disabled={busy || !rejectReason.trim()} onClick={() => void runAction(() => offCycleUseCases.rejectRun(run.id, rejectReason), 'Off-cycle run rejected.')} className={`${buttonClass} bg-rose-600 text-white hover:bg-rose-700`}>
                    <X className="h-4 w-4" aria-hidden="true" /> Reject
                  </button>
                </div>
              )}
              {canManage && can('MARK_PAID') && (
                <div className="flex items-end gap-2">
                  <label className={labelClass}>
                    Actual release date
                    <input type="date" value={actualPaymentDate} onChange={(event) => setActualPaymentDate(event.target.value)} className={inputClass} />
                  </label>
                  <button type="button" disabled={busy} onClick={() => void runAction(() => offCycleUseCases.markRunPaid(run.id, actualPaymentDate), 'Marked as paid. Amounts now count toward year-to-date tax.')} className={`${buttonClass} bg-emerald-600 text-white hover:bg-emerald-700`}>
                    <Wallet className="h-4 w-4" aria-hidden="true" /> Mark as paid
                  </button>
                </div>
              )}
              {canManage && can('DELETE') && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm('Delete this off-cycle run?')) {
                      void runAction(() => offCycleUseCases.deleteRun(run.id), 'Off-cycle run deleted.')
                    }
                  }}
                  className={`${buttonClass} border border-rose-200 bg-white text-rose-700 hover:bg-rose-50`}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" /> Delete
                </button>
              )}
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Employee</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                    <th className="px-3 py-2 text-right">Exempt (₱90k cap)</th>
                    <th className="px-3 py-2 text-right">Taxable</th>
                    <th className="px-3 py-2 text-right">Withholding tax</th>
                    <th className="px-3 py-2 text-right">Net pay</th>
                    <th className="px-3 py-2">Notes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {run.lines.map((line) => (
                    <tr key={line.id}>
                      <td className="px-3 py-1.5"><span className="font-medium">{line.employeeNo}</span> <span className="text-slate-500">{line.employeeName}</span></td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{money(line.amount)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{money(line.exemptLimitedAmount)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{money(line.taxableAmount)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{money(line.withholdingTax)}</td>
                      <td className="px-3 py-1.5 text-right font-semibold tabular-nums">{money(line.netAmount)}</td>
                      <td className="px-3 py-1.5 text-slate-600">{line.notes}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-slate-50 font-semibold">
                  <tr>
                    <td className="px-3 py-2">{run.lines.length} employee(s)</td>
                    <td className="px-3 py-2 text-right tabular-nums">{money(run.totalAmount)}</td>
                    <td className="px-3 py-2" />
                    <td className="px-3 py-2" />
                    <td className="px-3 py-2 text-right tabular-nums">{money(run.totalWithholdingTax)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{money(run.totalNetAmount)}</td>
                    <td className="px-3 py-2" />
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
