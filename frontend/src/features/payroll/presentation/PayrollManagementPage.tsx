import { useEffect, useState } from 'react'
import {
  BookOpenCheck,
  BriefcaseBusiness,
  Calculator,
  Gift,
  Settings2,
  Wallet,
} from 'lucide-react'
import TopNav, { type NavView } from '../../../components/dashboard/TopNav'
import { useCompanySetupSelection } from '../../../hooks/useCompanySetupSelection'
import CompensationManagement from './CompensationManagement'
import EarningRulesManagement from './EarningRulesManagement'
import GrossPayCalculation from './GrossPayCalculation'
import BenefitsManagement from './BenefitsManagement'
import EmployeeLoansManagement from './EmployeeLoansManagement'
import type { PayrollUseCases } from '../application/useCases'
import type {
  EmployeeLoan,
  PayrollCutoffOption,
  PayrollEmployeeOption,
  PayrollGroupOption,
} from '../domain/payroll'

interface Props {
  employeeName: string
  activeView: 'payroll-compensation' | 'payroll-earning-rules' | 'payroll-gross' | 'payroll-benefits' | 'payroll-deductions' | 'payroll-loans'
  useCases: PayrollUseCases
  canApprovePayroll: boolean
  canUnlockPayroll: boolean
  onNavigate?: (view: NavView) => void
  onLoggedOut?: () => void
}

const sections = [
  {
    view: 'payroll-compensation',
    label: 'Compensation',
    description: 'Employee base rates',
    icon: BriefcaseBusiness,
  },
  {
    view: 'payroll-earning-rules',
    label: 'Earning rules',
    description: 'Rate multipliers',
    icon: Settings2,
  },
  {
    view: 'payroll-benefits',
    label: 'Benefits',
    description: 'Manage recurring and per-cutoff benefits',
    icon: Gift,
  },
  {
    view: 'payroll-deductions',
    label: 'Deductions',
    description: 'Manage recurring and per-cutoff deductions',
    icon: Wallet,
  },
  {
    view: 'payroll-loans',
    label: 'Employee loans',
    description: 'Balances and repayments',
    icon: Wallet,
  },
  {
    view: 'payroll-gross',
    label: 'Payroll calculation',
    description: 'Calculate benefits and net pay',
    icon: Calculator,
  },
] as const

export default function PayrollManagementPage({
  employeeName,
  activeView,
  useCases,
  canApprovePayroll,
  canUnlockPayroll,
  onNavigate,
  onLoggedOut,
}: Props) {
  const { companyId } = useCompanySetupSelection()
  const [groups, setGroups] = useState<PayrollGroupOption[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [cutoffs, setCutoffs] = useState<PayrollCutoffOption[]>([])
  const [selectedCutoffId, setSelectedCutoffId] = useState('')
  const [employees, setEmployees] = useState<PayrollEmployeeOption[]>([])
  const [loans, setLoans] = useState<EmployeeLoan[]>([])
  const [loadingGroups, setLoadingGroups] = useState(false)
  const [loadingCutoffs, setLoadingCutoffs] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    setGroups([])
    setSelectedGroupId('')
    setCutoffs([])
    setSelectedCutoffId('')
    setError('')
    if (!companyId) return () => { current = false }

    setLoadingGroups(true)
    useCases.listPayrollGroups(companyId)
      .then((nextGroups) => {
        if (!current) return
        setGroups(nextGroups)
        setSelectedGroupId(nextGroups[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load payroll groups.')
      })
      .finally(() => {
        if (current) setLoadingGroups(false)
      })
    return () => {
      current = false
    }
  }, [companyId, useCases])

  useEffect(() => {
    let current = true
    setCutoffs([])
    setSelectedCutoffId('')
    if (!selectedGroupId || activeView !== 'payroll-gross') return () => { current = false }
    setLoadingCutoffs(true)
    useCases.listCutoffs(selectedGroupId)
      .then((nextCutoffs) => {
        if (!current) return
        setCutoffs(nextCutoffs)
        setSelectedCutoffId(nextCutoffs.find((cutoff) => !cutoff.locked)?.id ?? nextCutoffs[0]?.id ?? '')
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load payroll cutoffs.')
      })
      .finally(() => {
        if (current) setLoadingCutoffs(false)
      })
    return () => {
      current = false
    }
  }, [activeView, selectedGroupId, useCases])

  useEffect(() => {
    let current = true
    setLoans([])
    if (activeView !== 'payroll-loans' || !selectedGroupId) return () => { current = false }
    useCases.listEmployeeLoans(selectedGroupId)
      .then((nextLoans) => {
        if (current) setLoans(nextLoans)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load employee loans.')
      })
    return () => {
      current = false
    }
  }, [activeView, selectedGroupId, useCases])

  useEffect(() => {
    let current = true
    setEmployees([])
    if (!['payroll-gross', 'payroll-loans'].includes(activeView) || !selectedGroupId) return () => { current = false }
    useCases.listEmployees()
      .then((nextEmployees) => {
        if (current) setEmployees(nextEmployees)
      })
      .catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : 'Could not load employee names.')
      })
    return () => {
      current = false
    }
  }, [activeView, selectedGroupId, useCases])

  const selectedGroup = groups.find((group) => group.id === selectedGroupId)
  const groupLabel = selectedGroup ? `${selectedGroup.code} — ${selectedGroup.name}` : 'Selected payroll group'

  function selectGroup(nextGroupId: string) {
    setError('')
    setCutoffs([])
    setSelectedCutoffId('')
    setSelectedGroupId(nextGroupId)
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <TopNav employeeName={employeeName} activeView={activeView} onNavigate={onNavigate} onSignOut={onLoggedOut} />
      <main className="mx-auto w-[95%] max-w-7xl space-y-5 py-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="mt-1 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-100 text-indigo-700">
              <BookOpenCheck className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-indigo-600">HR workspace</p>
              <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Payroll management</h1>
              <p className="mt-1 text-sm text-slate-500">Configure employee rates, pay rules, and benefits, then calculate payroll for a cutoff.</p>
            </div>
          </div>
          {groups.length > 0 && (
            <label className="min-w-64 text-xs font-bold uppercase tracking-wide text-slate-500">
              Payroll group
              <select
                aria-label="Select payroll group"
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-semibold normal-case text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                value={selectedGroupId}
                onChange={(event) => selectGroup(event.target.value)}
              >
                {groups.map((group) => <option key={group.id} value={group.id}>{group.code} — {group.name}</option>)}
              </select>
            </label>
          )}
        </header>

        {error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {!companyId && (
          <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
            Select a company from the company selector above to view its payroll groups and setup.
          </section>
        )}
        {companyId && !loadingGroups && groups.length === 0 && !error && (
          <section className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
            No payroll groups are configured for this company. Set one up in Payroll → Payroll Groups first.
          </section>
        )}
        {loadingGroups && <p role="status" className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">Loading payroll groups…</p>}

        {selectedGroup && (
          <>
            <nav aria-label="Payroll workspace" className="grid grid-cols-1 gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm sm:grid-cols-2 lg:grid-cols-6">
              {sections.map((section) => {
                const Icon = section.icon
                const selected = section.view === activeView
                return (
                  <button
                    key={section.view}
                    type="button"
                    onClick={() => onNavigate?.(section.view)}
                    aria-current={selected ? 'page' : undefined}
                    className={`flex items-center gap-3 rounded-lg px-4 py-3 text-left transition ${selected ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-600 hover:bg-indigo-50 hover:text-indigo-700'}`}
                  >
                    <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
                    <span>
                      <span className="block text-sm font-bold">{section.label}</span>
                      <span className={`mt-0.5 block text-xs ${selected ? 'text-indigo-100' : 'text-slate-500'}`}>{section.description}</span>
                    </span>
                  </button>
                )
              })}
            </nav>

            {activeView === 'payroll-compensation' && (
              <CompensationManagement
                key={selectedGroup.id}
                companyId={companyId}
                payrollGroupId={selectedGroup.id}
                payrollGroupLabel={groupLabel}
                useCases={useCases}
              />
            )}
            {activeView === 'payroll-earning-rules' && (
              <EarningRulesManagement
                key={selectedGroup.id}
                payrollGroupId={selectedGroup.id}
                payrollGroupLabel={groupLabel}
                useCases={useCases}
              />
            )}
            {activeView === 'payroll-gross' && (
              <GrossPayCalculation
                key={selectedGroup.id}
                payrollGroupLabel={groupLabel}
                cutoffs={cutoffs}
                selectedCutoffId={selectedCutoffId}
                onSelectCutoff={setSelectedCutoffId}
                onCutoffLockChanged={(cutoffId, locked) => {
                  setCutoffs((current) => current.map((cutoff) => (
                    cutoff.id === cutoffId ? { ...cutoff, locked } : cutoff
                  )))
                }}
                employees={employees}
                useCases={useCases}
                canApprovePayroll={canApprovePayroll}
                canUnlockPayroll={canUnlockPayroll}
              />
            )}
            {(activeView === 'payroll-benefits' || activeView === 'payroll-deductions') && (
              <BenefitsManagement
                key={selectedGroup.id}
                payrollGroupId={selectedGroup.id}
                useCases={useCases}
                mode={activeView === 'payroll-benefits' ? 'entries' : 'payroll-deductions'}
              />
            )}
            {activeView === 'payroll-loans' && (
              <EmployeeLoansManagement
                key={selectedGroup.id}
                payrollGroupId={selectedGroup.id}
                employees={employees}
                loans={loans}
                useCases={useCases}
                onLoansChanged={setLoans}
              />
            )}
            {activeView === 'payroll-gross' && loadingCutoffs && (
              <p role="status" className="text-sm text-slate-500">Loading cutoffs…</p>
            )}
            {activeView === 'payroll-gross' && !loadingCutoffs && cutoffs.length === 0 && !error && (
              <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
                No payroll cutoffs are configured for this group yet.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  )
}
