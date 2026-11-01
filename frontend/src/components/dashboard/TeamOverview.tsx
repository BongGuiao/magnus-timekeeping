import { ArrowUpRight, ChevronDown, ClipboardCheck, Clock3, AlertTriangle, MapPin, Sparkles } from 'lucide-react'

export interface TeamOverviewItem {
  id: string
  label: string
  value?: string | number
  open: boolean
  controls?: string
  onClick: () => void
}

const categoryColors: Record<string, string> = {
  'missing-in': 'border-rose-200 bg-rose-50 text-rose-800 hover:bg-rose-100',
  'missing-out': 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100',
  hours: 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100',
  leave: 'border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100',
  'apply-leave': 'border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100',
  invalid: 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100',
  overtime: 'border-violet-200 bg-violet-50 text-violet-800 hover:bg-violet-100',
  ob: 'border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100',
  correction: 'border-teal-200 bg-teal-50 text-teal-800 hover:bg-teal-100',
  devices: 'border-rose-200 bg-rose-50 text-rose-800 hover:bg-rose-100',
  locations: 'border-cyan-200 bg-cyan-50 text-cyan-800 hover:bg-cyan-100',
  balances: 'border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100',
  attendance: 'border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100',
  payroll: 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100',
  updates: 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100',
  offline: 'border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100',
}

function displayValue(value: TeamOverviewItem['value']) {
  if (value === '—') return 'Not loaded'
  if (value === '…' || value === 'Loading…') return 'Loading...'
  return value
}

export default function TeamOverview({ role, metrics, reviews, employeeName }: {
  role: 'supervisor' | 'manager' | 'employee' | 'administrator'
  metrics: TeamOverviewItem[]
  reviews: TeamOverviewItem[]
  employeeName?: string
}) {
  const isEmployee = role === 'employee'
  const today = new Intl.DateTimeFormat('en-PH', {
    timeZone: 'Asia/Manila',
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date())
  return (
    <section aria-label={isEmployee ? 'Employee overview' : role === 'administrator' ? 'Organization overview' : 'Team overview'} className="overflow-hidden rounded-xl border border-indigo-100 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-indigo-100 bg-gradient-to-r from-indigo-100 via-indigo-50 to-sky-50 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
            <Sparkles size={18} aria-hidden="true" />
          </span>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600">{role} dashboard</p>
            <h1 className="text-lg font-bold text-indigo-950">
              {employeeName ? <>Welcome, <span className="text-indigo-700">{employeeName}</span></>
                : role === 'administrator' ? 'Organization overview' : isEmployee ? 'Welcome' : 'Team overview'}
            </h1>
            <p className="text-[11px] text-slate-500">{isEmployee ? 'Your attendance, filings and payroll' : 'Attendance this month · Hours this week'}</p>
          </div>
        </div>
        <div className="rounded-xl bg-gradient-to-br from-indigo-950 to-violet-900 p-2 shadow-sm">
          <div className="rounded-lg border border-white/15 bg-white/10 px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-wide text-indigo-200">Today</p>
            <p className="mt-0.5 text-xs font-semibold text-white">{today}</p>
          </div>
        </div>
      </header>
      {metrics.length > 0 && (
        <div className={`grid gap-2 p-3 ${isEmployee ? 'sm:grid-cols-2 lg:grid-cols-4' : 'sm:grid-cols-3'}`}>
          {metrics.map((item) => (
            <button key={item.id} type="button" aria-expanded={item.open} aria-controls={item.controls} onClick={item.onClick}
              className={`flex items-center justify-between gap-3 rounded-lg border border-l-4 px-3 py-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500 ${categoryColors[item.id] ?? 'border-slate-200 bg-slate-50 text-slate-800 hover:bg-slate-100'} ${item.open ? 'ring-2 ring-inset ring-current' : ''}`}>
              <span className="flex items-center gap-2 text-sm font-medium">
                {item.id === 'hours' ? <Clock3 size={16} aria-hidden="true" />
                  : item.id === 'leave' ? <ClipboardCheck size={16} aria-hidden="true" />
                    : <AlertTriangle size={16} aria-hidden="true" />}
                {item.label}
              </span>
              <span className={`shrink-0 font-bold tabular-nums ${typeof item.value === 'string' && ['—', '…', 'Loading…', 'Unavailable'].includes(item.value) ? 'text-xs' : 'whitespace-nowrap text-lg'}`}>{displayValue(item.value)}</span>
            </button>
          ))}
        </div>
      )}
      {reviews.length > 0 && (
        <div className="border-t border-slate-100 px-4 py-3">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
            <ClipboardCheck size={16} aria-hidden="true" /> {isEmployee ? 'My actions & records' : 'Review queue'}
          </h2>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {reviews.map((item) => (
              <button key={item.id} type="button" aria-expanded={!isEmployee || item.controls ? item.open : undefined} aria-controls={item.controls} onClick={item.onClick}
                className={`flex items-center gap-3 rounded-lg border border-l-4 px-3 py-2.5 text-left text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${categoryColors[item.id] ?? 'border-slate-200 bg-slate-50 text-slate-800 hover:bg-slate-100'} ${item.open ? 'ring-2 ring-inset ring-current' : ''}`}>
                <span className="flex-1 font-medium">{item.label}</span>
                {item.value !== undefined && <span className={`rounded-md px-2 py-0.5 text-xs font-bold tabular-nums ${!isEmployee && typeof item.value === 'number' && item.value > 0 ? 'bg-white ring-1 ring-current' : 'bg-white/80'}`}>{displayValue(item.value)}</span>}
                {item.id === 'locations' && <MapPin size={16} aria-hidden="true" />}
                {(!isEmployee || item.controls) && <ChevronDown size={14} aria-hidden="true" className={`shrink-0 transition-transform ${item.open ? 'rotate-180' : ''}`} />}
                {isEmployee && !item.controls && <ArrowUpRight size={16} aria-hidden="true" />}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">{isEmployee
            ? 'Arrow buttons open a module. Chevron buttons show or hide details. Only one detail panel opens at a time.'
            : 'Select a category to show or hide details. Highlighted counts need review. Only one panel opens at a time.'}</p>
        </div>
      )}
    </section>
  )
}
