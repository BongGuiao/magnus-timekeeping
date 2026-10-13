import type { DashboardRole } from '../../types/role'

interface Props {
  employeeFirstName: string
  role: DashboardRole
}

const roleDescriptions: Record<DashboardRole, string> = {
  administrator: 'Review organization-wide attendance, leave, and workforce activity.',
  manager: 'Review your team’s attendance, leave requests, and work hours.',
  supervisor: 'Monitor shift attendance and follow up on exceptions.',
  employee: 'Review your attendance, leave balances, and time records.',
}

export default function HeroBanner({ employeeFirstName, role }: Props) {
  return (
    <div className="flex flex-col justify-between gap-3 rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950 p-5 sm:flex-row sm:items-center">
      <div>
        <span className="inline-block rounded-full border border-indigo-400/30 bg-indigo-500/10 px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-indigo-300">
          {role} dashboard
        </span>
        <h1 className="mt-3 text-2xl font-extrabold text-white">
          Welcome back, {employeeFirstName}! <span aria-hidden>👋</span>
        </h1>
        <p className="mt-1 max-w-xl text-sm text-slate-300">
          {roleDescriptions[role]}
        </p>
      </div>

      <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">System Status</p>
          <p className="text-sm font-semibold text-white">Clocked In &amp; Syncing</p>
        </div>
      </div>
    </div>
  )
}
