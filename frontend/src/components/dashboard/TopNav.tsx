import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  BadgeCheck,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  CalendarRange,
  Calculator,
  ChartColumn,
  ChevronDown,
  Clock3,
  ClipboardCheck,
  FileClock,
  Gift,
  Landmark,
  LayoutDashboard,
  MapPin,
  MapPinned,
  Megaphone,
  MoreVertical,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Upload,
  UsersRound,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { fetchCompanies, fetchPayrollParameterCompanies } from '../../lib/companyApi'
import type { Company } from '../../types/company'
import { useCompanySetupSelection } from '../../hooks/useCompanySetupSelection'
import {
  getAvailableRoleCodes,
  canPreviewDashboardRoles,
  hasPermission,
  hasAnyPermission,
  getSelectedDashboardRoleCode,
  normalizeDashboardRole,
} from '../../types/role'

export type NavView =
  | 'dashboard'
  | 'enrollment'
  | 'attendance'
  | 'attendance-detail-report'
  | 'attendance-recalculation'
  | 'my-schedule'
  | 'schedule-uploads'
  | 'schedule-upload-approvals'
  | 'emergency-schedule-approvals'
  | 'companies'
  | 'org-units'
  | 'locations'
  | 'geofences'
  | 'employees'
  | 'payroll-groups'
  | 'payroll-cutoffs'
  | 'payroll-compensation'
  | 'payroll-earning-rules'
  | 'payroll-management'
  | 'payroll-gross'
  | 'payroll-benefits'
  | 'payroll-deductions'
  | 'payroll-loans'
  | 'company-benefit-types'
  | 'company-deduction-types'
  | 'payroll-statutory'
  | 'payroll-thirteenth-month'
  | 'payroll-off-cycle'
  | 'payroll-system-parameters'
  | 'payroll-review'
  | 'schedule-templates'
  | 'rest-day-patterns'
  | 'leave-management'
  | 'calendar'
  | 'announcements'
  | 'employee-entitlements'
  | 'leave-application'
  | 'overtime-application'
  | 'official-business'
  | 'change-password'

const companySetupTabViews: NavView[] = [
  'companies',
  'org-units',
  'locations',
  'geofences',
  'schedule-templates',
  'rest-day-patterns',
  'leave-management',
  'calendar',
  'announcements',
  'company-benefit-types',
  'company-deduction-types',
]

const payrollManagementViews: NavView[] = [
  'payroll-management',
  'payroll-groups',
  'payroll-cutoffs',
  'payroll-compensation',
  'payroll-earning-rules',
  'payroll-gross',
  'payroll-benefits',
  'payroll-deductions',
  'payroll-loans',
  'payroll-thirteenth-month',
  'payroll-off-cycle',
]

const companyContextViews: NavView[] = [
  ...companySetupTabViews,
  'payroll-statutory',
  'payroll-system-parameters',
  'payroll-groups',
  'payroll-cutoffs',
  'payroll-compensation',
  'payroll-earning-rules',
  'payroll-management',
  'payroll-gross',
  'payroll-benefits',
  'payroll-deductions',
  'payroll-loans',
  'company-benefit-types',
  'company-deduction-types',
  'payroll-thirteenth-month',
  'payroll-off-cycle',
]

interface NavLink {
  label: string
  view?: NavView
  permission?: string | string[]
  adminOnly?: boolean
  hasDropdown?: boolean
  children?: NavLink[]
}

const viewIcons: Partial<Record<NavView, LucideIcon>> = {
  dashboard: LayoutDashboard,
  attendance: ClipboardCheck,
  'attendance-detail-report': ChartColumn,
  'attendance-recalculation': RefreshCw,
  'my-schedule': CalendarDays,
  'schedule-uploads': Upload,
  'emergency-schedule-approvals': Clock3,
  companies: Building2,
  'org-units': Building2,
  locations: MapPin,
  geofences: MapPinned,
  employees: UsersRound,
  'payroll-groups': UsersRound,
  'payroll-cutoffs': CalendarRange,
  'payroll-compensation': BriefcaseBusiness,
  'payroll-earning-rules': SlidersHorizontal,
  'payroll-management': Wallet,
  'payroll-gross': Calculator,
  'payroll-benefits': Gift,
  'payroll-deductions': Wallet,
  'payroll-loans': Landmark,
  'company-benefit-types': Gift,
  'company-deduction-types': Wallet,
  'payroll-statutory': Landmark,
  'payroll-thirteenth-month': Calculator,
  'payroll-off-cycle': Gift,
  'payroll-system-parameters': SlidersHorizontal,
  'payroll-review': FileClock,
  'schedule-templates': CalendarDays,
  'rest-day-patterns': CalendarRange,
  'leave-management': BriefcaseBusiness,
  calendar: CalendarDays,
  announcements: Megaphone,
  'employee-entitlements': BadgeCheck,
  'leave-application': FileClock,
  'overtime-application': Clock3,
  'official-business': BriefcaseBusiness,
}

const labelIcons: Record<string, LucideIcon> = {
  Dashboard: LayoutDashboard,
  Timekeeping: Clock3,
  Reports: ChartColumn,
  People: UsersRound,
  Settings: Settings2,
  'Company Setup': Building2,
  Organization: Building2,
  'Work Rules': SlidersHorizontal,
  'Payroll Setup': Wallet,
  Payroll: Wallet,
}

function iconForLink(link: NavLink): LucideIcon | undefined {
  return (link.view ? viewIcons[link.view] : undefined) ?? labelIcons[link.label]
}

const navLinks: NavLink[] = [
  { label: 'Dashboard', view: 'dashboard' },
  {
    label: 'Timekeeping',
    children: [
      {
        label: 'Attendance',
        view: 'attendance',
        permission: ['attendance.read_own', 'attendance.read_team', 'attendance.read_org'],
      },
      {
        label: 'Attendance Recalculation',
        view: 'attendance-recalculation',
        permission: ['attendance.read_own', 'attendance.read_team', 'attendance.read_org'],
      },
      { label: 'Emergency CWS', view: 'my-schedule', permission: 'schedule.read_own' },
      {
        label: 'Emergency Schedule Approvals',
        view: 'emergency-schedule-approvals',
        permission: 'schedule.approve_emergency',
      },
      { label: 'Team Schedule Upload', view: 'schedule-uploads', permission: 'schedule.upload_team' },
    ],
  },
  {
    label: 'Reports',
    children: [
      {
        label: 'Attendance Detail',
        view: 'attendance-detail-report',
        permission: ['attendance.read_own', 'attendance.read_team', 'attendance.read_org', 'payroll.manage'],
      },
      {
        label: 'Payroll Calculation Review',
        view: 'payroll-review',
        permission: ['attendance.read_own', 'attendance.read_team', 'attendance.read_org', 'payroll.manage'],
      },
    ],
  },
  {
    label: 'People',
    children: [
      { label: 'Employees', view: 'employees', permission: ['employees.read', 'employees.read_team'] },
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
              { label: 'Companies', view: 'companies', permission: 'company.setup' },
              { label: 'Org Units', view: 'org-units', permission: 'company.setup' },
              { label: 'Locations', view: 'locations', permission: 'company.setup' },
              { label: 'Geofences', view: 'geofences', permission: 'company.setup' },
            ],
          },
          {
            label: 'Work Rules',
            children: [
              { label: 'Schedule Templates', view: 'schedule-templates', permission: 'schedule.manage' },
              { label: 'Rest Day Patterns', view: 'rest-day-patterns', permission: 'schedule.manage' },
              { label: 'Leave Management', view: 'leave-management', permission: 'leave.manage' },
            ],
          },
          {
            label: 'Payroll Setup',
            children: [
            { label: 'Benefit Types', view: 'company-benefit-types', permission: 'payroll.manage' },
            { label: 'Deduction Types', view: 'company-deduction-types', permission: 'payroll.manage' },
            { label: 'Calendar', view: 'calendar', permission: 'leave.manage' },
            { label: 'Announcements', view: 'announcements', permission: 'system.manage' },
            ],
          },
        ],
      },
      {
        label: 'Statutory Setup',
        children: [
          { label: 'Contribution & Tax Schedules', view: 'payroll-statutory', permission: 'payroll.company_parameters.manage' },
          { label: 'Company Parameters', view: 'payroll-system-parameters', permission: 'payroll.company_parameters.manage' },
        ],
      },
    ],
  },
  {
    label: 'Payroll',
    children: [
      { label: 'Payroll Cutoffs', view: 'payroll-cutoffs', permission: 'payroll.manage' },
      { label: 'Payroll Groups', view: 'payroll-groups', permission: 'payroll.manage' },
      { label: 'Management', view: 'payroll-management', permission: 'payroll.manage' },
      { label: 'Employee Loans', view: 'payroll-loans', permission: 'payroll.manage' },
      { label: '13th-Month Calculation', view: 'payroll-thirteenth-month', permission: 'payroll.manage' },
      { label: 'Off-Cycle Payroll', view: 'payroll-off-cycle', permission: ['payroll.manage', 'payroll.approve'] },
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
      <span className="sr-only">Choose an assigned dashboard role</span>
      <span aria-hidden="true">View as</span>
      <select
        aria-label="View dashboard as assigned role"
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

export default function TopNav({ activeView, onNavigate, onSignOut }: Props) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false)
  const [navHeight, setNavHeight] = useState(0)
  const navRef = useRef<HTMLElement>(null)
  const companySetupNavRef = useRef<HTMLElement>(null)
  const accountMenuRef = useRef<HTMLDivElement>(null)
  const mobileAccountMenuRef = useRef<HTMLDivElement>(null)
  const [companies, setCompanies] = useState<Company[]>([])
  const [companyLoadError, setCompanyLoadError] = useState('')
  const [roleCode, setRoleCode] = useState<string>(getSelectedDashboardRoleCode)
  const roleCodes = getAvailableRoleCodes()
  const canPreviewRoles = canPreviewDashboardRoles()
  const hasMultipleAssignedDashboardRoles = new Set(
    roleCodes.map((availableRoleCode) => normalizeDashboardRole(availableRoleCode)),
  ).size > 1
  const showDashboardRoleSelect = canPreviewRoles || hasMultipleAssignedDashboardRoles
  const isAdmin = normalizeDashboardRole(localStorage.getItem('role')) === 'administrator'
  const { companyId, selectCompany } = useCompanySetupSelection()
  const isCompanyContextView = companyContextViews.includes(activeView)
  const filterByPermission = (link: NavLink): NavLink | null => {
    if (link.adminOnly && !isAdmin) return null
    if (typeof link.permission === 'string' && !hasPermission(link.permission)) return null
    if (Array.isArray(link.permission) && !hasAnyPermission(link.permission)) return null
    const children = link.children?.map(filterByPermission).filter((child): child is NavLink => child !== null)
    if (link.children && children?.length === 0) return null
    return { ...link, children }
  }
  const visibleNavLinks = navLinks
    .map(filterByPermission)
    .filter((link): link is NavLink => link !== null)
    .map((link) => {
      const children = link.children?.map((child) => {
        if (child.label !== 'Company Setup') return child
        return {
          ...child,
          children: companyId
            ? child.children
            : child.children?.map((section) => ({
              ...section,
              children: section.children?.filter((setupChild) => setupChild.view === 'companies'),
            })).filter((section) => (section.children?.length ?? 0) > 0),
        }
      })
      return { ...link, children }
    })
  const companySetupSections = visibleNavLinks
    .find((link) => link.label === 'Settings')
    ?.children?.find((link) => link.label === 'Company Setup')
    ?.children ?? []
  const companySetupTabs = companySetupSections.flatMap((section) => section.children ?? [])

  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return

    const updateNavHeight = () => setNavHeight(nav.getBoundingClientRect().height)
    updateNavHeight()
    const observer = new ResizeObserver(updateNavHeight)
    observer.observe(nav)
    return () => observer.disconnect()
  }, [])

  useLayoutEffect(() => {
    if (activeView !== 'company-deduction-types') return
    const setupNav = companySetupNavRef.current
    if (!setupNav) return
    setupNav.scrollTo({ left: setupNav.scrollWidth, behavior: 'smooth' })
  }, [activeView, companyId])

  useEffect(() => {
    if (!isCompanyContextView) return
    let isCurrent = true
    const loadCompanies = activeView === 'payroll-system-parameters'
      ? fetchPayrollParameterCompanies
      : fetchCompanies
    loadCompanies()
      .then((items) => {
        if (!isCurrent) return
        setCompanies(items)
        setCompanyLoadError('')
        if (companyId && !items.some((company) => company.id === companyId)) {
          selectCompany('')
        } else if (!companyId && items.length === 1 && items[0].id) {
          selectCompany(items[0].id)
        }
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          setCompanyLoadError(error instanceof Error ? error.message : 'Could not load companies.')
          setCompanies([])
        }
      })
    return () => {
      isCurrent = false
    }
  }, [activeView, companyId, isCompanyContextView, selectCompany])

  useEffect(() => {
    if (!isAccountMenuOpen) return
    function closeOnOutsideClick(event: PointerEvent) {
      if (
        event.target instanceof Node
        && !accountMenuRef.current?.contains(event.target)
        && !mobileAccountMenuRef.current?.contains(event.target)
      ) {
        setIsAccountMenuOpen(false)
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setIsAccountMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [isAccountMenuOpen])

  function navigateTo(view?: NavView) {
    if (view) onNavigate?.(view)
    setIsAccountMenuOpen(false)
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
    <>
    <header ref={navRef} className="fixed inset-x-0 top-0 z-50 border-b border-slate-200 bg-white">
      <div className="mx-auto flex w-[95%] items-center justify-between py-3">
        <img src="/TimeLogo.jpg" alt="Magnus Business Solutions Inc." className="h-16 w-52 object-contain" />

        <div className="flex min-w-0 items-center gap-4 xl:gap-6">
          <nav className="hidden items-center gap-5 xl:flex 2xl:gap-6">
            {visibleNavLinks.map((link) => link.children ? (
              <div key={link.label} className="group relative">
                <button
                  type="button"
                  className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium transition ${
                    link.children.some((child) => child.view === activeView)
                      || (link.label === 'Payroll' && payrollManagementViews.includes(activeView))
                      || (link.label === 'Settings' && (
                        companySetupTabViews.includes(activeView)
                        || activeView === 'payroll-statutory'
                        || activeView === 'payroll-system-parameters'
                      ))
                      ? 'bg-indigo-50 text-indigo-700'
                      : 'text-slate-900 hover:bg-slate-50 hover:text-indigo-600'
                  }`}
                >
                  {(() => {
                    const Icon = iconForLink(link)
                    return Icon ? <Icon className="h-4 w-4" aria-hidden="true" /> : null
                  })()}
                  {link.label}
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                <div className={`invisible absolute top-full z-30 pt-3 opacity-0 transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 ${link.label === 'Settings' ? 'right-0' : 'left-0'}`}>
                  <div className={`rounded-lg border border-slate-200 bg-white p-3 shadow-lg ${link.label === 'Settings' ? 'w-[min(34rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)]' : 'min-w-44'}`}>
                    {link.children.map((child) => child.label === 'Company Setup' && child.children ? (
                      <section key={child.label}>
                        <h2 className="mb-3 border-b border-slate-100 px-1 pb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                          {(() => {
                            const Icon = iconForLink(child)
                            return Icon ? <Icon className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" /> : null
                          })()}
                          {child.label}
                        </h2>
                        <div className="settings-submenu-scroll flex max-w-full gap-3 overflow-x-auto pb-2">
                          {child.children.map((section) => (
                            <div key={section.label} className="w-48 shrink-0 rounded-xl border border-slate-100 bg-slate-50/80 p-2">
                              <h3 className="mb-1 flex items-center gap-1.5 px-2 text-xs font-bold uppercase tracking-wide text-slate-400">
                                {(() => {
                                  const Icon = iconForLink(section)
                                  return Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null
                                })()}
                                {section.label}
                              </h3>
                              {section.children?.map((setupLink) => (
                                <button
                                  key={setupLink.label}
                                  type="button"
                                  onClick={() => navigateTo(setupLink.view)}
                                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm font-semibold transition-colors ${setupLink.view === activeView ? 'bg-indigo-100 text-indigo-700 shadow-sm' : 'text-slate-900 hover:bg-white hover:text-indigo-700'}`}
                                >
                                  {(() => {
                                    const Icon = iconForLink(setupLink)
                                    return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                                  })()}
                                  {setupLink.label}
                                </button>
                              ))}
                            </div>
                          ))}
                        </div>
                      </section>
                    ) : child.label === 'Statutory Setup' && child.children ? (
                      <section key={child.label} className="min-w-60">
                        <h2 className="mb-2 border-b border-slate-100 px-2 pb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                          {child.label}
                        </h2>
                        {child.children.map((setupLink) => (
                          <button
                            key={setupLink.label}
                            type="button"
                            onClick={() => navigateTo(setupLink.view)}
                            className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold transition-colors ${setupLink.view === activeView ? 'bg-indigo-100 text-indigo-700 shadow-sm' : 'text-slate-900 hover:bg-slate-50 hover:text-indigo-700'}`}
                          >
                            {(() => {
                              const Icon = iconForLink(setupLink)
                              return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                            })()}
                            {setupLink.label}
                          </button>
                        ))}
                      </section>
                    ) : (
                      <button
                        key={child.label}
                        type="button"
                        onClick={() => navigateTo(child.view)}
                        className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold ${child.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-900 hover:bg-slate-50'}`}
                      >
                        {(() => {
                          const Icon = iconForLink(child)
                          return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                        })()}
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
                className={`flex items-center gap-1.5 text-sm font-medium transition hover:text-indigo-600 ${
                  link.view === activeView ? 'text-indigo-600' : 'text-slate-900'
                }`}
              >
                {(() => {
                  const Icon = iconForLink(link)
                  return Icon ? <Icon className="h-4 w-4" aria-hidden="true" /> : null
                })()}
                {link.label}
                {link.hasDropdown && <ChevronDown className="h-3.5 w-3.5 text-slate-400" />}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            {showDashboardRoleSelect && (
              <div className="hidden text-right leading-tight xl:block">
                <DashboardRoleSelect roleCode={roleCode} roleCodes={roleCodes} onChange={changeDashboardRole} />
              </div>
            )}
            <button
              type="button"
              onClick={signOut}
              className="hidden rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-semibold text-rose-600 transition hover:bg-rose-50 xl:block"
            >
              Sign Out
            </button>
            <div ref={accountMenuRef} className="relative hidden xl:block">
              <button
                type="button"
                aria-label="More account options"
                aria-haspopup="menu"
                aria-expanded={isAccountMenuOpen}
                onClick={() => setIsAccountMenuOpen((isOpen) => !isOpen)}
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
              >
                <MoreVertical className="h-4 w-4" aria-hidden="true" />
              </button>
              {isAccountMenuOpen && (
                <div role="menu" aria-label="Account options" className="absolute right-0 top-full z-40 mt-2 min-w-48 rounded-lg border border-slate-200 bg-white p-1.5 shadow-lg">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => navigateTo('change-password')}
                    aria-current={activeView === 'change-password' ? 'page' : undefined}
                    className={`block w-full rounded-md px-3 py-2 text-left text-sm font-semibold transition ${
                      activeView === 'change-password'
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'text-slate-900 hover:bg-slate-50'
                    }`}
                  >
                    Change Password
                  </button>
                </div>
              )}
            </div>
            <button
              type="button"
              aria-label="Toggle navigation menu"
              aria-expanded={isMobileMenuOpen}
              aria-controls="mobile-navigation"
              onClick={() => setIsMobileMenuOpen((isOpen) => !isOpen)}
              className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-white text-2xl leading-none text-slate-700 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 xl:hidden"
            >
              {isMobileMenuOpen ? '×' : '≡'}
            </button>
          </div>
        </div>
      </div>

      {isMobileMenuOpen && (
        <nav id="mobile-navigation" className="absolute left-0 top-full z-40 w-full border-t border-slate-100 bg-white px-[2.5%] py-3 shadow-lg xl:hidden">
          <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
            {showDashboardRoleSelect && (
              <DashboardRoleSelect roleCode={roleCode} roleCodes={roleCodes} onChange={changeDashboardRole} />
            )}
            <div className="flex shrink-0 items-center gap-2">
              <button type="button" onClick={signOut} className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-50">
                Sign Out
              </button>
              <div ref={mobileAccountMenuRef} className="relative">
                <button
                  type="button"
                  aria-label="More account options"
                  aria-haspopup="menu"
                  aria-expanded={isAccountMenuOpen}
                  onClick={() => setIsAccountMenuOpen((isOpen) => !isOpen)}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                >
                  <MoreVertical className="h-4 w-4" aria-hidden="true" />
                </button>
                {isAccountMenuOpen && (
                  <div role="menu" aria-label="Account options" className="absolute right-0 top-full z-40 mt-2 min-w-48 rounded-lg border border-slate-200 bg-white p-1.5 shadow-lg">
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => navigateTo('change-password')}
                      aria-current={activeView === 'change-password' ? 'page' : undefined}
                      className={`block w-full rounded-md px-3 py-2 text-left text-sm font-semibold transition ${
                        activeView === 'change-password'
                          ? 'bg-indigo-50 text-indigo-700'
                          : 'text-slate-900 hover:bg-slate-50'
                      }`}
                    >
                      Change Password
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="space-y-4">
            {visibleNavLinks.map((group) => (
              <div key={group.label}>
                {group.children ? (
                  <>
                    <p className="mb-1 flex items-center gap-1.5 px-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      {(() => {
                        const Icon = iconForLink(group)
                        return Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null
                      })()}
                      {group.label}
                    </p>
                    {group.label === 'Settings' ? (
                      <div className="space-y-3">
                        {group.children.find((link) => link.label === 'Company Setup')?.children?.map((section) => (
                          <section key={section.label}>
                            <h3 className="mb-1 flex items-center gap-1.5 px-1 text-xs font-bold uppercase tracking-wide text-slate-400">
                              {(() => {
                                const Icon = iconForLink(section)
                                return Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null
                              })()}
                              {section.label}
                            </h3>
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                              {section.children?.map((link) => (
                                <button
                                  key={link.label}
                                  type="button"
                                  onClick={() => navigateTo(link.view)}
                                  className={`flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                                    link.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-900 hover:bg-slate-50'
                                  }`}
                                >
                                  {(() => {
                                    const Icon = iconForLink(link)
                                    return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                                  })()}
                                  {link.label}
                                </button>
                              ))}
                            </div>
                          </section>
                        ))}
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {group.children.map((link) => link.label === 'Statutory Setup' && link.children ? (
                          <section key={link.label}>
                            <h3 className="mb-1 flex items-center gap-1.5 px-1 text-xs font-bold uppercase tracking-wide text-slate-400">
                              <Landmark className="h-3.5 w-3.5" aria-hidden="true" />
                              {link.label}
                            </h3>
                            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                              {link.children.map((setupLink) => (
                                <button
                                  key={setupLink.label}
                                  type="button"
                                  onClick={() => navigateTo(setupLink.view)}
                                  className={`flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                                    setupLink.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-900 hover:bg-slate-50'
                                  }`}
                                >
                                  {(() => {
                                    const Icon = iconForLink(setupLink)
                                    return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                                  })()}
                                  {setupLink.label}
                                </button>
                              ))}
                            </div>
                          </section>
                        ) : (
                          <button
                            key={link.label}
                            type="button"
                            onClick={() => navigateTo(link.view)}
                            className={`flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                              link.view === activeView ? 'bg-indigo-50 text-indigo-700' : 'text-slate-900 hover:bg-slate-50'
                            }`}
                          >
                            {(() => {
                              const Icon = iconForLink(link)
                              return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                            })()}
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
                    className={`flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold transition ${
                      group.view === activeView
                        ? 'bg-indigo-50 text-indigo-700'
                        : group.view
                          ? 'text-slate-900 hover:bg-slate-50'
                          : 'cursor-not-allowed text-slate-400'
                    }`}
                  >
                    {(() => {
                      const Icon = iconForLink(group)
                      return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                    })()}
                    {group.label}
                  </button>
                )}
              </div>
            ))}
          </div>
        </nav>
      )}

      {companyContextViews.includes(activeView) && (
        <div className="mx-auto w-[95%] border-b border-indigo-200 pt-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              {activeView === 'payroll-system-parameters' && companies.length === 1
                ? (
                  <>
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Company</span>
                    <span className="min-w-64 rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-700">
                      {companies[0].company_code} — {companies[0].legal_name}
                    </span>
                  </>
                )
                : (
                  <>
                    <label className="text-xs font-bold uppercase tracking-wide text-slate-500" htmlFor="company-context-selector">
                      Company
                    </label>
                    <select
                      id="company-context-selector"
                      aria-label="Select company for payroll or company setup"
                      value={companyId}
                      onChange={(event) => selectCompany(event.target.value)}
                      className="min-w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                    >
                      <option value="">Select a company</option>
                      {companies.map((company) => (
                        <option key={company.id} value={company.id}>
                          {company.company_code} — {company.legal_name}
                        </option>
                      ))}
                    </select>
                  </>
                )}
              {companyId && (
                <span className="text-xs font-medium text-indigo-700">
                  {activeView.startsWith('payroll-')
                    ? 'Payroll is scoped to the selected company.'
                    : 'Setup is scoped to the selected company.'}
                </span>
              )}
            </div>
          </div>
          {!companyId && (
            <p className="mb-3 text-sm text-slate-500">
              {activeView === 'payroll-system-parameters' && !companyLoadError
                ? 'System Parameters use your active company assignment. If no company appears, verify your assignment and permissions.'
                : activeView.startsWith('payroll-')
                  ? 'Select a company to load its payroll groups.'
                  : 'Select a company to open its setup tabs.'}
            </p>
          )}
          {companyLoadError && <p role="alert" className="mb-2 text-sm text-rose-700">{companyLoadError}</p>}
          {companyId && !activeView.startsWith('payroll-') && (
            <nav ref={companySetupNavRef} aria-label="Company setup" className="flex gap-0 overflow-x-auto pb-1">
              {companySetupTabs.map((link, index, links) => (
                  <button
                    key={link.label}
                    type="button"
                    onClick={() => navigateTo(link.view)}
                    aria-current={link.view === activeView ? 'step' : undefined}
                    className={`relative shrink-0 px-6 py-3 text-sm font-semibold transition ${
                      link.view === activeView
                        ? 'z-10 bg-indigo-600 text-white'
                        : 'bg-slate-100 text-slate-900 hover:bg-indigo-50 hover:text-indigo-700'
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
                    {(() => {
                      const Icon = iconForLink(link)
                      return Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden="true" /> : null
                    })()}
                    {link.label}
                  </button>
                ))}
            </nav>
          )}
        </div>
      )}

    </header>
    <div aria-hidden="true" style={{ height: `${navHeight}px` }} />
    </>
  )
}
