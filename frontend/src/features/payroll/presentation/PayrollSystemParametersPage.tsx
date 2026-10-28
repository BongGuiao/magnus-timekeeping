import { useEffect, useState, type FormEvent } from 'react'
import TopNav, { type NavView } from '../../../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../../../hooks/useCompanySetupSelection'
import type { PayrollUseCases } from '../application/useCases'

interface Props {
  employeeName: string
  useCases: PayrollUseCases
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function PayrollSystemParametersPage({
  employeeName,
  useCases,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { companyId } = useCompanySetupSelection()
  const [yearEndWtaxReconciliationEnabled, setYearEndWtaxReconciliationEnabled] = useState(false)
  const [yearEndWtaxReconciliationDraft, setYearEndWtaxReconciliationDraft] = useState(false)
  const [thirteenthMonthEnabled, setThirteenthMonthEnabled] = useState(false)
  const [thirteenthMonthDraft, setThirteenthMonthDraft] = useState(false)
  const [scheduleAssignmentApprovalRequired, setScheduleAssignmentApprovalRequired] = useState(true)
  const [scheduleAssignmentApprovalRequiredDraft, setScheduleAssignmentApprovalRequiredDraft] =
    useState(true)
  const [statutoryContributionTiming, setStatutoryContributionTiming] =
    useState<'PER_CUTOFF' | 'FINAL_CUTOFF'>('PER_CUTOFF')
  const [loadedCompanyId, setLoadedCompanyId] = useState('')
  const [loadErrorCompanyId, setLoadErrorCompanyId] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const loading = Boolean(companyId)
    && loadedCompanyId !== companyId
    && loadErrorCompanyId !== companyId

  useEffect(() => {
    let current = true
    if (!companyId) return () => { current = false }
    useCases.getPayrollSystemParameters(companyId)
      .then((parameters) => {
        if (!current) return
        setYearEndWtaxReconciliationEnabled(parameters.yearEndWtaxReconciliationEnabled)
        setYearEndWtaxReconciliationDraft(parameters.yearEndWtaxReconciliationEnabled)
        setThirteenthMonthEnabled(parameters.thirteenthMonthEnabled)
        setThirteenthMonthDraft(parameters.thirteenthMonthEnabled)
        setScheduleAssignmentApprovalRequired(parameters.scheduleAssignmentApprovalRequired)
        setScheduleAssignmentApprovalRequiredDraft(parameters.scheduleAssignmentApprovalRequired)
        setStatutoryContributionTiming(parameters.statutoryContributionTiming)
        setLoadedCompanyId(companyId)
        setLoadErrorCompanyId('')
        setSaved(false)
        setError('')
      })
      .catch((cause: unknown) => {
        if (current) {
          setLoadErrorCompanyId(companyId)
          setError(cause instanceof Error
            ? cause.message
            : 'Could not load payroll system parameters.')
        }
      })
    return () => { current = false }
  }, [companyId, useCases])

  async function saveParameters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!companyId) return
    setSaving(true)
    setSaved(false)
    setError('')
    try {
      const result = await useCases.updatePayrollSystemParameters(companyId, {
        yearEndWtaxReconciliationEnabled: yearEndWtaxReconciliationDraft,
        thirteenthMonthEnabled: thirteenthMonthDraft,
        scheduleAssignmentApprovalRequired: scheduleAssignmentApprovalRequiredDraft,
        statutoryContributionTiming,
      })
      setYearEndWtaxReconciliationEnabled(result.yearEndWtaxReconciliationEnabled)
      setYearEndWtaxReconciliationDraft(result.yearEndWtaxReconciliationEnabled)
      setThirteenthMonthEnabled(result.thirteenthMonthEnabled)
      setThirteenthMonthDraft(result.thirteenthMonthEnabled)
      setScheduleAssignmentApprovalRequired(result.scheduleAssignmentApprovalRequired)
      setScheduleAssignmentApprovalRequiredDraft(result.scheduleAssignmentApprovalRequired)
      setStatutoryContributionTiming(result.statutoryContributionTiming)
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error
        ? cause.message
        : 'Could not update payroll system parameters.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView="payroll-system-parameters"
        onNavigate={onNavigate}
        onSignOut={onLoggedOut}
      />
      <main className="w-full space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <header>
          <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Company Setup</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Company Parameters</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Configure payroll calculations and schedule behavior for the selected company. Changes apply after they are saved.
          </p>
        </header>

        {error && (
          <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </p>
        )}

        {!companyId && (
          <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
            Your assigned company is loading, or there is no active company assignment available for your System Parameters access.
          </section>
        )}
        {companyId && loading && (
          <p role="status" className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
            Loading payroll parameters for the selected company…
          </p>
        )}

        {companyId && loadedCompanyId === companyId && (
        <form onSubmit={(event) => void saveParameters(event)} className="space-y-5">
          <section className="rounded-xl border border-indigo-100 bg-indigo-50 p-5">
            <div className="flex flex-wrap items-start justify-between gap-5">
              <div className="max-w-3xl">
                <h2 className="text-base font-bold text-slate-900">Year-end WTAX reconciliation</h2>
                <p className="mt-1 text-sm text-slate-600">
                  When enabled, the final active December cutoff compares year-to-date tax withheld
                  with annual tax due, calculated from the semi-monthly withholding-tax table using
                  24 payroll periods. The adjustment may be a deduction or a refund.
                </p>
                <p className="mt-2 text-xs text-slate-500">
                  Recalculate earlier payroll cutoffs first so the year-to-date totals are current.
                  This applies only to semi-monthly schedules and employees included in the final
                  December cutoff.
                </p>
              </div>
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={yearEndWtaxReconciliationDraft}
                  disabled={loading || saving || loadedCompanyId !== companyId}
                  onChange={(event) => {
                    setYearEndWtaxReconciliationDraft(event.target.checked)
                    setSaved(false)
                  }}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                Enable year-end WTAX true-up
              </label>
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-5">
              <div className="max-w-3xl">
                <h2 className="text-base font-bold text-slate-900">13th-month pay calculation</h2>
                <p className="mt-1 text-sm text-slate-600">
                  Allow payroll users to calculate 13th-month pay using eligible basic salary earned
                  during the year, including eligible paid leave. The active tax schedule&apos;s
                  exemption limit is shared with other qualifying benefits; ₱90,000 is recommended.
                </p>
              </div>
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={thirteenthMonthDraft}
                  disabled={loading || saving || loadedCompanyId !== companyId}
                  onChange={(event) => {
                    setThirteenthMonthDraft(event.target.checked)
                    setSaved(false)
                  }}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                Enable 13th-month calculation
              </label>
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-5">
              <div className="max-w-3xl">
                <h2 className="text-base font-bold text-slate-900">Schedule assignment approval</h2>
                <p className="mt-1 text-sm text-slate-600">
                  When enabled, direct employee schedule assignments and schedule-upload batches
                  require approval before they take effect. When disabled, new direct assignments
                  and supervisor uploads are approved immediately.
                </p>
                <p className="mt-2 text-xs text-slate-500">
                  Changing this setting does not automatically approve assignments or upload
                  batches that are already awaiting review. If an upload includes employees from
                  multiple companies, it requires approval when any of those companies requires it.
                </p>
              </div>
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                <input
                  type="checkbox"
                  checked={scheduleAssignmentApprovalRequiredDraft}
                  disabled={loading || saving || loadedCompanyId !== companyId}
                  onChange={(event) => {
                    setScheduleAssignmentApprovalRequiredDraft(event.target.checked)
                    setSaved(false)
                  }}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                Require schedule approval
              </label>
            </div>
          </section>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={!companyId || loading || saving || loadedCompanyId !== companyId
                || (
                  yearEndWtaxReconciliationDraft === yearEndWtaxReconciliationEnabled
                  && thirteenthMonthDraft === thirteenthMonthEnabled
                  && scheduleAssignmentApprovalRequiredDraft === scheduleAssignmentApprovalRequired
                )}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? 'Loading…' : saving ? 'Saving…' : 'Save parameters'}
            </button>
            {saved && (
              <p role="status" className="text-sm font-medium text-emerald-700">
                Payroll system parameters saved.
              </p>
            )}
          </div>
        </form>
        )}
      </main>
    </div>
  )
}
