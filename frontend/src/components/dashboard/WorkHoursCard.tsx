import type { WorkHoursSummary } from '../../types/dashboard'

interface Props {
  hours: WorkHoursSummary
  weeklyHoursWorked?: number | null
  isWeeklyHoursLoading?: boolean
}

function ProgressBar({ value, target }: { value: number; target: number }) {
  const percent = target > 0 ? Math.min(100, Math.round((value / target) * 100)) : 0
  return (
    <div className="mt-2 h-2 w-full rounded-full bg-slate-100">
      <div className="h-2 rounded-full bg-indigo-500" style={{ width: `${percent}%` }} />
    </div>
  )
}

function formatHours(value: number): string {
  const totalMinutes = Math.round(value * 60)
  return `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m`
}

export default function WorkHoursCard({
  hours,
  weeklyHoursWorked,
  isWeeklyHoursLoading = false,
}: Props) {
  const displayWeeklyHours = weeklyHoursWorked ?? 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-500">Work Hours</h2>

      <div className="mt-3">
        <div className="flex items-baseline justify-between">
          <p className="text-xs text-slate-500">This week</p>
          <p className="text-sm font-semibold text-slate-900">
            {isWeeklyHoursLoading ? 'Loading…' : `${formatHours(displayWeeklyHours)} / ${hours.weeklyTarget}h`}
          </p>
        </div>
        <ProgressBar value={displayWeeklyHours} target={hours.weeklyTarget} />
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between">
          <p className="text-xs text-slate-500">This month</p>
          <p className="text-sm font-semibold text-slate-900">
            {hours.monthlyHours}h / {hours.monthlyTarget}h
          </p>
        </div>
        <ProgressBar value={hours.monthlyHours} target={hours.monthlyTarget} />
      </div>
    </div>
  )
}
