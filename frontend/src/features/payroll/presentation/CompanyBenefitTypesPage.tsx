import { useEffect, useState } from 'react'
import { Gift } from 'lucide-react'
import TopNav, { type NavView } from '../../../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../../../hooks/useCompanySetupSelection'
import type { PayrollUseCases } from '../application/useCases'
import type { PayrollGroupOption } from '../domain/payroll'
import BenefitsManagement from './BenefitsManagement'

interface Props {
  employeeName: string
  useCases: PayrollUseCases
  setupType: 'benefits' | 'deductions'
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

export default function CompanyBenefitTypesPage({
  employeeName,
  useCases,
  setupType,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { companyId } = useCompanySetupSelection()
  const [groups, setGroups] = useState<PayrollGroupOption[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    setGroups([])
    setSelectedGroupId('')
    setError('')
    if (!companyId) return () => { current = false }

    setLoading(true)
    useCases.listPayrollGroups(companyId)
      .then((nextGroups) => {
        if (!current) return
        setGroups(nextGroups)
        setSelectedGroupId(nextGroups[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load company payroll groups.')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => { current = false }
  }, [companyId, useCases])

  const selectedGroup = groups.find((group) => group.id === selectedGroupId)

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav
        employeeName={employeeName}
        activeView={setupType === 'benefits' ? 'company-benefit-types' : 'company-deduction-types'}
        onNavigate={onNavigate}
        onSignOut={onLoggedOut}
      />
      <main className="w-full space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="mt-1 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-100 text-indigo-700">
              <Gift className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">Company setup</p>
              <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
                {setupType === 'benefits' ? 'Benefit types' : 'Deduction types'}
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                Configure {setupType === 'benefits' ? 'benefit rules' : 'non-statutory deduction rules'} for the selected company’s payroll group.
              </p>
            </div>
          </div>
          {groups.length > 0 && (
            <label className="min-w-64 text-xs font-bold uppercase tracking-wide text-slate-500">
              Payroll group
              <select
                aria-label="Select payroll group for benefit types"
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold normal-case text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                value={selectedGroupId}
                onChange={(event) => setSelectedGroupId(event.target.value)}
              >
                {groups.map((group) => (
                  <option key={group.id} value={group.id}>{group.code} — {group.name}</option>
                ))}
              </select>
            </label>
          )}
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!companyId && (
          <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
            Select a company from the company selector above to configure its benefit types.
          </section>
        )}
        {loading && <p role="status" className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">Loading payroll groups…</p>}
        {companyId && !loading && groups.length === 0 && !error && (
          <section className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
            No payroll groups are configured for this company. Set one up in Payroll → Payroll Groups first.
          </section>
        )}
        {selectedGroup && (
          <BenefitsManagement
            key={`${setupType}-${selectedGroup.id}`}
            payrollGroupId={selectedGroup.id}
            useCases={useCases}
            mode={setupType === 'benefits' ? 'types' : 'deductions'}
          />
        )}
      </main>
    </div>
  )
}
