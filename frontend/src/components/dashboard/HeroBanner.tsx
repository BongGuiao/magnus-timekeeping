import type { DashboardRole } from '../../types/role'

interface Props {
  employeeName: string
  role: DashboardRole
}

const roleDescriptions: Record<DashboardRole, string> = {
  administrator: 'Review organization-wide attendance, leave, and workforce activity.',
  manager: 'Review your team’s attendance, leave requests, and work hours.',
  supervisor: 'Monitor shift attendance and follow up on exceptions.',
  employee: 'Review your attendance, leave balances, and time records.',
}

export default function HeroBanner({ employeeName, role }: Props) {
  const now = new Date()
  const greeting = now.getHours() < 12
    ? 'Good morning'
    : now.getHours() < 18
      ? 'Good afternoon'
      : 'Good evening'
  const today = new Intl.DateTimeFormat(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(now)

  return (
    <section className="relative isolate overflow-hidden rounded-2xl border border-indigo-300/20 bg-gradient-to-br from-slate-950 via-indigo-950 to-violet-900 px-5 py-4 shadow-lg shadow-indigo-950/10 sm:px-7 sm:py-5">
      <div className="pointer-events-none absolute -right-16 -top-28 h-56 w-56 rounded-full bg-indigo-400/20 blur-3xl" aria-hidden="true" />
      <div className="pointer-events-none absolute -bottom-40 right-1/3 h-48 w-48 rounded-full bg-violet-400/10 blur-3xl" aria-hidden="true" />
      <div className="relative flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="max-w-2xl">
          <span className="inline-flex rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-indigo-100 shadow-sm backdrop-blur">
            {role} dashboard
          </span>
          <h1 className="mt-2.5 text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
            {greeting} {employeeName}!
          </h1>
          <p className="mt-1 max-w-xl text-sm leading-5 text-indigo-100/80">
            {roleDescriptions[role]}
          </p>
        </div>

        <div className="shrink-0 rounded-xl border border-white/15 bg-white/10 px-4 py-3 shadow-md shadow-slate-950/10 backdrop-blur-md sm:min-w-56">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-indigo-200/75">Today</p>
            <p className="mt-0.5 text-sm font-semibold leading-5 text-white">{today}</p>
          </div>
        </div>
      </div>
    </section>
  )
}
