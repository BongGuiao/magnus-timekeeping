import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { fetchCompanies } from '../../lib/companyApi'
import type { Company } from '../../types/company'
import { useCompanySetupSelection } from '../../hooks/useCompanySetupSelection'
import {
  getAvailableRoleCodes,
  getSelectedDashboardRoleCode,
  getSelectedDashboardRole,
  type DashboardRole,
} from '../../types/role'

export type NavView =
  | 'dashboard'
  | 'enrollment'
  | 'attendance'
  | 'companies'
  | 'org-units'
  | 'locations'
  | 'geofences'
  | 'employees'
  | 'payroll-groups'
  | 'payroll-cutoffs'
  | 'schedule-templates'
  | 'rest-day-patterns'
  | 'leave-management'
  | 'employee-entitlements'
  | 'leave-application'
  | 'overtime-application'
  | 'official-business'

const companySetupViews: NavView[] = [
  'companies',
  'org-units',
  'locations',
  'geofences',
  'payroll-groups',
  'payroll-cutoffs',
  'schedule-templates',
  'rest-day-patterns',
  'leave-management',
]

interface NavLink {
  label: string
  view?: NavView
  hasDropdown?: boolean
  children?: NavLink[]
}

const navLinks: NavLink[] = [
  { label: 'Dashboard', view: 'dashboard' },
  {
    label: 'Timekeeping',
    children: [
      { label: 'Attendance', view: 'attendance' },
    ],
  },
  { label: 'Reports', hasDropdown: true },
  {
    label: 'People',
    children: [
      { label: 'Employees', view: 'employees' },
    ],
  },
  {
    label: 'Settings',
    children: [
      {
        label: 'Company Setup',
        view: 'companies',
        children: [
          {
            label: 'Organization',
            children: [
              { label: 'Companies', view: 'companies' },
              { label: 'Org Units', view: 'org-units' },
              { label: 'Locations', view: 'locations' },
              { label: 'Geofences', view: 'geofences' },
            ],
          },
          {
            label: 'Payroll',
            children: [
              { label: 'Payroll Groups', view: 'payroll-groups' },
              { label: 'Payroll Cutoffs', view: 'payroll-cutoffs' },
            ],
          },
          {
            label: 'Work Rules',
            children: [
              { label: 'Schedule Templates', view: 'schedule-templates' },
              { label: 'Rest Day Patterns', view: 'rest-day-patterns' },
              { label: 'Leave Management', view: 'leave-management' },
            ],
          },
        ],
      },
    ],
  },
]

interface Props {
  employeeName: string
  activeView: NavView
  onNavigate?: (view: NavView) => void
  onSignOut?: () => void
}

function DashboardRoleSelect({
  roleCode,
  roleCodes,
  onChange,
}: {
  roleCode: string
  roleCodes: string[]
  onChange: (roleCode: string) => void
}) {
  return (
    <label className="flex items-center gap-2 text-xs font-semibold text-slate-500">
      <span className="sr-only">Preview dashboard as</span>
      <span aria-hidden="true">View as</span>
      <select
        aria-label="Preview dashboard as role"
        value={roleCode}
        disabled={roleCodes.length === 0}
        onChange={(event) => onChange(event.target.value)}
        className="max-w-36 rounded-md border border-indigo-100 bg-indigo-50 px-2 py-1 text-xs font-bold capitalize text-indigo-700 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
      >
        {roleCodes.length > 0
          ? roleCodes.map((availableRoleCode) => (
            <option key={availableRoleCode} value={availableRoleCode}>
              {availableRoleCode}
            </option>
          ))
          : <option value="">No roles assigned</option>}
      </select>
    </label>
  )
}

export default function TopNav({ employeeName, activeView, onNavigate, onSignOut }: Props) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [companies, setCompanies] = useState<Company[]>([])
  const [companyLoadError, setCompanyLoadError] = useState('')
  const [roleCode, setRoleCode] = useState<string>(getSelectedDashboardRoleCode)
  const roleCodes = getAvailableRoleCodes()
  const role: DashboardRole = getSelectedDashboardRole()
  const hasLeaveAdminAccess = localStorage.getItem('role') === 'admin'
  const { companyId, selectCompany } = useCompanySetupSelection()
  const isCompanySetupView = companySetupViews.includes(activeView)
  const visibleNavLinks = navLinks.map((link) => {
    const children = link.children?.map((child) => {
      if (child.label !== 'Company Setup') return child
      const setupChildren = child.children?.map((section) => ({
        ...section,
        children: section.children?.filter((setupChild) =>
          (setupChild.view !== 'leave-management' && setupChild.view !== 'payroll-groups'
            && setupChild.view !== 'payroll-cutoffs' && setupChild.view !== 'schedule-templates'
            && setupChild.view !== 'rest-day-patterns')
          || hasLeaveAdminAccess,
        ),
      })).filter((section) => (section.children?.length ?? 0) > 0)
      return {
        ...child,
        children: companyId
          ? setupChildren
          : setupChildren?.map((section) => ({
            ...section,
            children: section.children?.filter((setupChild) => setupChild.view === 'companies'),
          })).filter((section) => (section.children?.length ?? 0) > 0),
      }
    })
    return { ...link, children }
  }).filter((link) => {
    if (link.view === 'leave-application') return role === 'employee'
    return link.children === undefined || link.children.length > 0
  })
  const companySetupSections = visibleNavLinks
    .find((link) => link.label === 'Settings')
    ?.children?.find((link) => link.label === 'Company Setup')
    ?.children ?? []
  const companySetupTabs = companySetupSections.flatMap((section) => section.children ?? [])

  useEffect(() => {
    if (!isCompanySetupView) return
    let isCurrent = true
    fetchCompanies()
      .then((items) => {
        if (!isCurrent) return
        setCompanies(items)
        setCompanyLoadError('')
        if (companyId && !items.some((company) => company.id === companyId)) {
          selectCompany('')
        }
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          setCompanyLoadError(error instanceof Error ? error.message : 'Could not load companies.')
        }
      })
    return () => {
      isCurrent = false
    }
  }, [companyId, isCompanySetupView, selectCompany])

  function navigateTo(view?: NavView) {
    if (view) onNavigate?.(view)
    setIsMobileMenuOpen(false)
  }

  function signOut() {
    setIsMobileMenuOpen(false)
    onSignOut?.()
  }

  function changeDashboardRole(nextRoleCode: string) {
    setRoleCode(nextRoleCode)
    localStorage.setItem('dashboard_role_code', nextRoleCode)
    window.dispatchEvent(new CustomEvent('dashboard-role-change'))
    navigateTo('dashboard')
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex w-[95%] items-center justify-between py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
            MT
          </div>
          <div className="leading-tight">
            <p className="text-base font-extrabold tracking-tight text-slate-900">
              MAGNUS<span className="text-indigo-600">TIME</span>
            </p>
            <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">Timekeeping Center</p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <nav className="hidden items-center gap-6 xl:flex">
            {visibleNavLinks.map((link) => link.children ? (
              <div key={link.label} className="group relative">
                <button
                  type="button"
                  className={`flex items-center gap-1 text-sm font-medium transition hover:text-indigo-600 ${
                    link.children.some((child) => child.view === activeView)
                      || (link.label === 'Settings' && companySetupViews.includes(activeView))
                      ? 'text-indigo-600'
                      : 'text-slate-600'
                  }`}
                >
                  {link.label}
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                <div className={`invisible absolute top-full z-30 pt-3 opacity-0 transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 ${link.label === 'Settings' ? 'right-0' : 'left-0'}`}>
                  <div className={`rounded-lg border border-slate-200 bg-white p-3 shadow-lg ${link.label === 'Settings' ? 'w-[min(34rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)]' : 'min-w-44'}`}>
                    {link.children.map((child) => child.label === 'Company Setup' && child.children ? (
                      <section key={child.label}>
                        <h2 className="mb-3 border-b border-slate-100 px-1 pb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                          {child.label}
                        </h2>
                        <div className="settings-submenu-scroll flex max-w-full gap-3 overflow-x-auto pb-2">
                          {child.children.map((section) => (
                            <div key={section.label} className="w-48 shrink-0 rounded-xl border border-slate-100 bg-slate-50/80 p-2">
                              <h3 className="mb-1 px-2 text-xs font-bold uppercase tracking-wide text-slate-400">{section.label}</h3>
                              {section.children?.map((setupLink) => (
                                <button
                                  key={setupLink.label}
                                  type="button"
                                  onClick={() => navigateTo(setupLink.view)}
                                  className={`block w-full rounded-lg px-2 py-2 text-left text-sm font-semibold transition-colors ${setupLink.view === activeView ? 'bg-indigo-100 text-indigo-700 shadow-sm' : 'text-slate-700 hover:bg-white hover:text-indigo-700'}`}
                                >
                                  {setupLink.label}
                                </button>
                              ))}
                            </div>
                          ))}
                        </div>
                      </section>
                    ) : (
                      <button
                        key={child.label}
                        type="button"
                        onClick={() => navigateTo(child.view)}
                        className={`block w-full rounded-md px-3 py-2 text-left text-sm font-semibold ${child.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700 hover:bg-slate-50'}`}
                      >
                        {child.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <a
                key={link.label}
                href="#"
                onClick={(event) => {
                  event.preventDefault()
                  if (link.view) onNavigate?.(link.view)
                }}
                className={`flex items-center gap-1 text-sm font-medium transition hover:text-indigo-600 ${
                  link.view === activeView ? 'text-indigo-600' : 'text-slate-600'
                }`}
              >
                {link.label}
                {link.hasDropdown && <ChevronDown className="h-3.5 w-3.5 text-slate-400" />}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="hidden text-right leading-tight sm:block">
              <p className="text-sm font-semibold text-slate-900">{employeeName}</p>
              <DashboardRoleSelect roleCode={roleCode} roleCodes={roleCodes} onChange={changeDashboardRole} />
            </div>
            <button
              type="button"
              onClick={signOut}
              className="hidden rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-semibold text-rose-600 transition hover:bg-rose-50 sm:block"
            >
              Sign Out
            </button>
            <button
              type="button"
              aria-label="Toggle navigation menu"
              aria-expanded={isMobileMenuOpen}
              aria-controls="mobile-navigation"
              onClick={() => setIsMobileMenuOpen((isOpen) => !isOpen)}
              className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-white text-2xl leading-none text-slate-700 transition hover:bg-slate-50 xl:hidden"
            >
              {isMobileMenuOpen ? '×' : '≡'}
            </button>
          </div>
        </div>
      </div>

      {isMobileMenuOpen && (
        <nav id="mobile-navigation" className="border-t border-slate-100 bg-white px-[2.5%] py-3 xl:hidden">
          <div className="mb-3 flex items-center justify-between border-b border-slate-100 pb-3 sm:hidden">
            <div className="leading-tight">
              <p className="text-sm font-semibold text-slate-900">{employeeName}</p>
              <DashboardRoleSelect roleCode={roleCode} roleCodes={roleCodes} onChange={changeDashboardRole} />
            </div>
            <button type="button" onClick={signOut} className="text-sm font-semibold text-rose-600">
              Sign Out
            </button>
          </div>
          <div className="space-y-4">
            {visibleNavLinks.map((group) => (
              <div key={group.label}>
                {group.children ? (
                  <>
                    <p className="mb-1 px-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      {group.label}
                    </p>
                    {group.label === 'Settings' ? (
                      <div className="space-y-3">
                        {group.children.find((link) => link.label === 'Company Setup')?.children?.map((section) => (
                          <section key={section.label}>
                            <h3 className="mb-1 px-1 text-xs font-bold uppercase tracking-wide text-slate-400">{section.label}</h3>
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                              {section.children?.map((link) => (
                                <button
                                  key={link.label}
                                  type="button"
                                  onClick={() => navigateTo(link.view)}
                                  className={`min-h-11 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                                    link.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700 hover:bg-slate-50'
                                  }`}
                                >
                                  {link.label}
                                </button>
                              ))}
                            </div>
                          </section>
                        ))}
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {group.children.map((link) => (
                          <button
                            key={link.label}
                            type="button"
                            onClick={() => navigateTo(link.view)}
                            className={`min-h-11 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                              link.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700 hover:bg-slate-50'
                            }`}
                          >
                            {link.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => navigateTo(group.view)}
                    disabled={!group.view}
                    className={`min-h-11 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                      group.view === activeView
                        ? 'bg-indigo-50 text-indigo-700'
                        : group.view
                          ? 'text-slate-700 hover:bg-slate-50'
                          : 'cursor-not-allowed text-slate-400'
                    }`}
                  >
                    {group.label}
                  </button>
                )}
              </div>
            ))}
          </div>
        </nav>
      )}

      {companySetupViews.includes(activeView) && (
        <div className="mx-auto w-[95%] border-b border-indigo-200 pt-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-xs font-bold uppercase tracking-wide text-slate-500" htmlFor="company-setup-selector">
                Company
              </label>
              <select
                id="company-setup-selector"
                aria-label="Select company for company setup"
                value={companyId}
                onChange={(event) => selectCompany(event.target.value)}
                className="min-w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              >
                <option value="">Select a company to configure</option>
                {companies.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.company_code} — {company.legal_name}
                  </option>
                ))}
              </select>
              {companyId && <span className="text-xs font-medium text-indigo-700">Setup is scoped to the selected company.</span>}
            </div>
          </div>
          {!companyId && (
            <p className="mb-3 text-sm text-slate-500">Select a company to open its setup tabs.</p>
          )}
          {companyLoadError && <p role="alert" className="mb-2 text-sm text-rose-700">{companyLoadError}</p>}
          {companyId && (
            <nav aria-label="Company setup" className="flex gap-0 overflow-x-auto pb-1">
              {companySetupTabs.map((link, index, links) => (
                  <button
                    key={link.label}
                    type="button"
                    onClick={() => navigateTo(link.view)}
                    aria-current={link.view === activeView ? 'step' : undefined}
                    className={`relative shrink-0 px-6 py-3 text-sm font-semibold transition ${
                      link.view === activeView
                        ? 'z-10 bg-indigo-600 text-white'
                        : 'bg-slate-100 text-slate-600 hover:bg-indigo-50 hover:text-indigo-700'
                    }`}
                    style={{
                      clipPath: index === 0
                        ? 'polygon(0 0, calc(100% - 14px) 0, 100% 50%, calc(100% - 14px) 100%, 0 100%)'
                        : index === links.length - 1
                          ? 'polygon(0 0, calc(100% - 14px) 0, 100% 50%, calc(100% - 14px) 100%, 0 100%, 14px 50%)'
                          : 'polygon(0 0, calc(100% - 14px) 0, 100% 50%, calc(100% - 14px) 100%, 0 100%, 14px 50%)',
                      marginLeft: index === 0 ? 0 : -10,
                    }}
                  >
                    {link.label}
                  </button>
                ))}
            </nav>
          )}
        </div>
      )}

    </header>
  )
}
